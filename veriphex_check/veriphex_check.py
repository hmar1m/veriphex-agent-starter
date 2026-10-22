#!/usr/bin/env python3
"""veriphex-check: what Veriphex will think of an agent package, before you submit it.

    veriphex-check <link> --key cosign.pub --tools tools.txt [--password TOKEN]
    veriphex-check --practice-log practice.log --tools tools.txt

The first form reads the package from its registry, as Veriphex does at submission, and says in
plain sentences whether it is signed with your key, whether it carries anything that looks like a
secret, whether it has a linux/amd64 version, and which files are large enough to be an AI model.
The second reads the log the practice door printed during a practice run and names every call to
a tool tools.txt does not declare, and every direct internet attempt.

The signature check is the one Veriphex runs: cosign's legacy format, a `sha256-<hex>.sig` tag
whose layers are simple-signing payloads, each signed ECDSA P-256 / SHA-256 in its
`dev.cosignproject.cosign/signature` annotation, naming the package's digest.

Registry access goes through RegistryClient, so it can be replaced in tests. Needs `requests` and
`cryptography`.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import tarfile

LARGE_FILE_BYTES = 200 * 1024 * 1024
SCAN_CONTENT_BYTES = 10 * 1024 * 1024
SIMPLE_SIGNING = 'application/vnd.dev.cosign.simplesigning.v1+json'
SIGNATURE_ANNOTATION = 'dev.cosignproject.cosign/signature'
LINK = re.compile(r'^(?P<host>[a-z0-9.-]+(?::\d+)?)/(?P<repo>[a-z0-9._/-]+)@(?P<digest>sha256:[0-9a-f]{64})$')
INDEX_TYPES = ('application/vnd.oci.image.index.v1+json',
               'application/vnd.docker.distribution.manifest.list.v2+json')
ACCEPT = ', '.join(INDEX_TYPES + ('application/vnd.oci.image.manifest.v1+json',
                                  'application/vnd.docker.distribution.manifest.v2+json'))

LARGE_FILE_SENTENCE = ('This package carries a large file ({name}, {size}). If it is an AI model, declare it '
                       'on the form. The standard machine has no GPU and 8 GB of memory.')

SECRET_PATTERNS = [
    ('a private key', re.compile(rb'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED |PGP )?PRIVATE KEY(?: BLOCK)?-----')),
    ('an AWS access key', re.compile(rb'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b')),
    ('a Google API key', re.compile(rb'\bAIza[0-9A-Za-z_\-]{35}\b')),
    ('a Google service account key', re.compile(rb'"type"\s*:\s*"service_account"')),
    ('an Anthropic API key', re.compile(rb'\bsk-ant-[A-Za-z0-9_\-]{20,}')),
    ('an OpenAI API key', re.compile(rb'\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9]{20,}')),
    ('a GitHub token', re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})')),
]


class RegistryError(Exception):
    """The registry could not be read."""


class NotFound(RegistryError):
    """The registry answered that the manifest or blob does not exist."""


class RegistryClient:
    """The OCI distribution API, anonymously first, then with the read-only password.

    The password is `gcloud auth print-access-token` (user oauth2accesstoken) or a key file's JSON
    (user _json_key). It is held in memory for this run only.
    """

    def __init__(self, host, password=None, http=None):
        import requests
        self.host = host
        self.http = http or requests.Session()
        self.password = password
        self._auth = None

    def _basic(self):
        if not self.password:
            return None
        user = '_json_key' if self.password.lstrip().startswith('{') else 'oauth2accesstoken'
        return (user, self.password)

    def _get(self, path, headers=None, stream=False):
        url = f'https://{self.host}/v2/{path}'
        headers = dict(headers or {})
        if self._auth:
            headers['Authorization'] = self._auth
        resp = self.http.get(url, headers=headers, stream=stream, timeout=60)
        if resp.status_code == 401 and not self._auth:
            self._auth = self._authorise(resp.headers.get('WWW-Authenticate', ''))
            if self._auth:
                headers['Authorization'] = self._auth
                resp = self.http.get(url, headers=headers, stream=stream, timeout=60)
        if resp.status_code == 404:
            raise NotFound(path)
        if resp.status_code != 200:
            raise RegistryError(f'{path}: HTTP {resp.status_code}')
        return resp

    def _authorise(self, challenge):
        basic = self._basic()
        if challenge.lower().startswith('bearer '):
            params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
            realm = params.pop('realm', '')
            if not realm:
                return None
            resp = self.http.get(realm, params=params, auth=basic, timeout=60)
            if resp.status_code != 200:
                return None
            body = resp.json()
            token = body.get('token') or body.get('access_token')
            return f'Bearer {token}' if token else None
        if basic:
            raw = f'{basic[0]}:{basic[1]}'.encode()
            return 'Basic ' + base64.b64encode(raw).decode()
        return None

    def get_manifest(self, repository, reference):
        """(raw bytes, media type) of a manifest or index."""
        resp = self._get(f'{repository}/manifests/{reference}', {'Accept': ACCEPT})
        return resp.content, resp.headers.get('Content-Type', '').split(';')[0]

    def open_blob(self, repository, digest):
        """A readable stream of a blob."""
        resp = self._get(f'{repository}/blobs/{digest}', stream=True)
        resp.raw.decode_content = False
        return resp.raw


def _human_size(n):
    if n >= 1024 ** 3:
        return f'{n / 1024 ** 3:.1f} GB'
    return f'{n / 1024 ** 2:.0f} MB'


def read_tools(path):
    """Tool names from tools.txt: one per line; blank lines and # comments ignored."""
    names = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.split('#', 1)[0].strip()
            if line:
                names.append(line.split()[0])
    return names


def verify_signature(payload, signature_b64, public_key_pem):
    """True when the DER ECDSA P-256 / SHA-256 signature over payload verifies under the key."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = serialization.load_pem_public_key(public_key_pem)
    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != 'secp256r1':
        raise ValueError('the key is not an ECDSA P-256 public key')
    try:
        key.verify(base64.b64decode(signature_b64), payload, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError):
        return False


class Report:
    def __init__(self):
        self.lines = []
        self.problems = 0
        self.signed = None          # 'yes', 'other_key', 'other_package', 'unsigned', 'unknown'
        self.amd64 = None
        self.secrets = []           # (file, kind)
        self.large_files = []       # (file, size)

    def good(self, sentence):
        self.lines.append(sentence)

    def bad(self, sentence):
        self.problems += 1
        self.lines.append(sentence)

    @property
    def ok(self):
        return self.problems == 0


def _check_signature(client, repo, digest, public_key_pem, key_name, report):
    sig_tag = digest.replace(':', '-') + '.sig'
    try:
        raw, _ = client.get_manifest(repo, sig_tag)
    except NotFound:
        report.signed = 'unsigned'
        report.bad("That package isn't signed. Sign it with cosign and your registered key "
                   "(cosign sign --key cosign.key --new-bundle-format=false <link>), then check again.")
        return
    except RegistryError:
        report.signed = 'unknown'
        report.bad("veriphex-check couldn't read the package's signature.")
        return
    manifest = json.loads(raw)
    matched_other_digest = False
    for layer in manifest.get('layers', []):
        if layer.get('mediaType') != SIMPLE_SIGNING:
            continue
        signature = (layer.get('annotations') or {}).get(SIGNATURE_ANNOTATION)
        if not signature:
            continue
        stream = client.open_blob(repo, layer['digest'])
        payload = stream.read()
        if 'sha256:' + hashlib.sha256(payload).hexdigest() != layer['digest']:
            continue
        if not verify_signature(payload, signature, public_key_pem):
            continue
        try:
            critical = json.loads(payload)['critical']
            signed_digest = critical['image']['docker-manifest-digest']
            kind = critical['type']
        except (ValueError, KeyError, TypeError):
            continue
        if kind == 'cosign container image signature' and signed_digest == digest:
            report.signed = 'yes'
            report.good(f'The package is signed with your key ({key_name}).')
            return
        matched_other_digest = True
    if matched_other_digest:
        report.signed = 'other_package'
        report.bad('That signature is for a different package.')
    else:
        report.signed = 'other_key'
        report.bad(f"That package wasn't signed with your key ({key_name}).")


def _scan_layer(stream, report):
    """Look through one layer's files for secrets and large files."""
    with tarfile.open(fileobj=stream, mode='r|*') as tar:
        for member in tar:
            name = '/' + member.name.lstrip('./')
            base = name.rsplit('/', 1)[-1]
            if base.startswith('.wh.') or not member.isreg():
                continue
            if member.size > LARGE_FILE_BYTES:
                report.large_files.append((name, member.size))
                continue
            if base == '.env' or base.startswith('.env.'):
                report.secrets.append((name, 'an .env file'))
                continue
            if member.size > SCAN_CONTENT_BYTES:
                continue
            fh = tar.extractfile(member)
            data = fh.read() if fh else b''
            for kind, pattern in SECRET_PATTERNS:
                if pattern.search(data):
                    report.secrets.append((name, kind))
                    break


def check_package(link, public_key_pem, key_name='cosign.pub', tools=None, client=None, password=None):
    """Check a package link and return a Report of plain sentences."""
    report = Report()
    m = LINK.match(link or '')
    if not m:
        report.bad('The package link must end with @sha256: and the fingerprint, like '
                   'us-central1-docker.pkg.dev/acme-agents/agents/invoice-checker@sha256:<64 characters>.')
        return report
    repo, digest = m.group('repo'), m.group('digest')
    client = client or RegistryClient(m.group('host'), password=password)
    try:
        raw, media_type = client.get_manifest(repo, digest)
    except RegistryError:
        report.bad("veriphex-check couldn't read that package. Check the link and the read-only password "
                   "(gcloud auth print-access-token).")
        return report
    if 'sha256:' + hashlib.sha256(raw).hexdigest() != digest:
        report.bad("The package at that link doesn't match its fingerprint.")
        return report

    _check_signature(client, repo, digest, public_key_pem, key_name, report)

    manifest = json.loads(raw)
    media_type = manifest.get('mediaType') or media_type
    image_manifest = None
    if media_type in INDEX_TYPES or 'manifests' in manifest:
        platforms = [(d.get('platform') or {}, d) for d in manifest.get('manifests', [])]
        amd64 = [d for p, d in platforms if p.get('os') == 'linux' and p.get('architecture') == 'amd64']
        report.amd64 = bool(amd64)
        chosen = amd64[0] if amd64 else next((d for p, d in platforms if p.get('os') not in (None, 'unknown')), None)
        if chosen:
            image_manifest = json.loads(client.get_manifest(repo, chosen['digest'])[0])
    else:
        image_manifest = manifest
        config = json.loads(client.open_blob(repo, manifest['config']['digest']).read())
        report.amd64 = config.get('os') == 'linux' and config.get('architecture') == 'amd64'
    if report.amd64:
        report.good('It has a version for Intel and AMD processors (linux/amd64).')
    else:
        report.bad('The package must include a version for Intel and AMD processors (linux/amd64).')

    unreadable = 0
    for layer in (image_manifest or {}).get('layers', []):
        try:
            _scan_layer(client.open_blob(repo, layer['digest']), report)
        except (tarfile.TarError, RegistryError, EOFError, OSError):
            unreadable += 1
    if unreadable:
        report.bad(f"veriphex-check couldn't read {unreadable} of the package's layers, so they were not "
                   "looked through for secrets.")
    if report.secrets:
        for name, kind in report.secrets:
            report.bad(f'{name} looks like it holds a secret ({kind}). Take it out of the package: an agent '
                       'reaches services only through the tools Veriphex gives it.')
    else:
        report.good('Nothing in it looks like a secret.')
    for name, size in report.large_files:
        report.lines.append(LARGE_FILE_SENTENCE.format(name=name, size=_human_size(size)))

    if tools is not None:
        report.good(f'tools.txt declares {len(tools)} tool{"s" if len(tools) != 1 else ""}: '
                    f'{", ".join(tools) or "none"}. A practice run shows whether the agent calls any other '
                    '(veriphex-check --practice-log).')
    return report


def check_practice_log(lines, declared_tools):
    """Plain sentences about a practice run, from the practice door's printed log.

    The door prints one `PRACTICE {json}` line per request: `{"kind": "mcp", "method", "tool"}` for
    tool requests and `{"kind": "internet", "destination"}` for anything sent past it.
    """
    declared = set(declared_tools)
    undeclared, internet, calls = [], [], 0
    for line in lines:
        if 'PRACTICE ' not in line:
            continue
        try:
            event = json.loads(line.split('PRACTICE ', 1)[1])
        except ValueError:
            continue
        if event.get('kind') == 'mcp' and event.get('method') == 'tools/call':
            calls += 1
            tool = event.get('tool') or ''
            if tool not in declared and tool not in undeclared:
                undeclared.append(tool)
        elif event.get('kind') == 'internet':
            dest = event.get('destination') or 'an unknown address'
            if dest not in internet:
                internet.append(dest)
    report = Report()
    for tool in undeclared:
        report.bad(f'The agent called {tool}, which tools.txt does not declare. Declare it on the form, '
                   'or Veriphex will refuse the call.')
    for dest in internet:
        report.bad(f'The agent tried to reach {dest} directly. In the sealed space that is refused '
                   'and reported; reach services through Veriphex tools instead.')
    if not undeclared and not internet:
        report.good(f'The practice run made {calls} tool call{"s" if calls != 1 else ""}, all to declared '
                    'tools, and tried no direct internet access.')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog='veriphex-check', description=__doc__.split('\n\n')[0])
    parser.add_argument('link', nargs='?', help='the package link, ending @sha256:<fingerprint>')
    parser.add_argument('--key', help='your cosign public key, e.g. cosign.pub')
    parser.add_argument('--tools', help='tools.txt, the tools the agent declares')
    parser.add_argument('--password', help='read-only registry password; or set VERIPHEX_REGISTRY_PASSWORD')
    parser.add_argument('--practice-log', help="the practice door's printed log")
    args = parser.parse_args(argv)

    tools = read_tools(args.tools) if args.tools else None
    if args.practice_log:
        if tools is None:
            parser.error('--practice-log needs --tools tools.txt')
        with open(args.practice_log, encoding='utf-8', errors='replace') as fh:
            report = check_practice_log(fh, tools)
    else:
        if not args.link or not args.key:
            parser.error('give the package link and --key cosign.pub')
        with open(args.key, 'rb') as fh:
            key = fh.read()
        password = args.password or os.environ.get('VERIPHEX_REGISTRY_PASSWORD') or None
        report = check_package(args.link, key, os.path.basename(args.key), tools, password=password)
    for line in report.lines:
        print(line)
    return 0 if report.ok else 1


if __name__ == '__main__':
    sys.exit(main())

# Bundled certificate revocation data

This directory contains Mozilla's OneCRL snapshot fetched from the official
Remote Settings service on 26 October 2026. The complete signed records, metadata
and certificate chain are retained; `manifest.json` records provenance, dates,
byte lengths and SHA-256 hashes. The snapshot has 1,907 entries, 1,262 enabled.
It is security data from Mozilla, not browser activity collected by Cyphra.

Gecko 158.0.1's Mozilla production-root verifier authenticated the P-384 content
signature and signing chain in an isolated native Linux profile. Timestamp and record tampering were rejected, and native certificate-storage installation returned success in a fresh, network-isolated profile. The exact
public signing key is pinned in `security-state.sys.mjs`. At startup Cyphra
validates local integrity and verifies that detached signature before applying
the enabled/disabled entries through native `nsICertStorage`. These operations
do not fetch remote configuration, contact a certificate authority, or upload
telemetry. The signature covers all records and their exact collection timestamp;
the metadata's separate modification time is not that signing timestamp.

The signing certificate is valid from 6 September until 25 November 2026. The
pinned public-key signature continues to authenticate this historical snapshot
after certificate expiry; expiry does not disable browsing. A new signing key
must be reviewed, qualified against Mozilla's production root, and pinned in a
new Cyphra release. An unrecognized or invalid data signature fails closed.

OneCRL is not a complete live revocation service or phishing database. The
dataset's age is reported as an actual snapshot date. Maintain it through
reviewed Cyphra releases; this distribution does not perform continuous online
OCSP, CRLite or Safe Browsing updates. Do not call this continuously current
revocation protection.

Maintainers can prepare a future release snapshot with Python 3.12+ and Node
22+, using the browser's own detached-signature verifier:

```sh
python3 scripts/refresh-security-data.py --verify-local browser/security
python3 scripts/refresh-security-data.py --output artifacts/onecrl-candidate
```

The first command is offline and writes nothing. The second fetches only the
bounded official Mozilla records, metadata and signing chain over verified
HTTPS, rejects redirects, pagination and an older snapshot, and writes a new
candidate directory only after the current pinned key authenticates it. It
never changes shipped data or the browser's network policy. A signature or key
change fails with instructions to review and qualify the new signer against
Gecko's Mozilla production root before changing the source pin.

Review the candidate's four data files and actual dates/counts, then replace
the four matching source files in this directory. Keep this README. Update
the snapshot count assertions in `tests/security-state.test.mjs`, run the tests
and qualify native certificate-storage installation before packaging. A new
candidate's manifest records detached-signature verification and preserves
the prior production-root qualification of its signing key separately; the
helper does not claim it ran Gecko or performed a new production-root test.

Primary sources:

- [Official OneCRL records](https://firefox.settings.services.mozilla.com/v1/buckets/security-state/collections/onecrl/records)
- [Official collection metadata](https://firefox.settings.services.mozilla.com/v1/buckets/security-state/collections/onecrl)
- [Gecko Remote Settings documentation](https://firefox-source-docs.mozilla.org/services/settings/index.html)
- [Mozilla revocation model](https://wiki.mozilla.org/CA/Revocation_Checking_in_Firefox)

Gecko's surrounding implementation is MPL-2.0. Preserve Mozilla source and data
attribution when distributing this snapshot.

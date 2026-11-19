# Signing the Windows build

Waypoint ships an unsigned `Waypoint.exe` today. Signing it with an Authenticode
certificate is what removes "Windows protected your PC" (SmartScreen), and it is the
one change that makes antivirus heuristics and mod-host scanners trust the archive
without a human review.

**This file explains how to get a certificate and how to plug it in. Nothing in this
repository can create one: a certificate certifies an identity, and only a certificate
authority can vouch for it. A self-signed certificate proves the plumbing and nothing
else — do not ship a build signed with one.**

## What a certificate costs

| route | price | notes |
|---|---|---|
| [SignPath Foundation](https://signpath.org/) | free for open source | application reviewed by humans; signs in CI through their GitHub app, key never leaves them |
| [Certum Open Source Code Signing](https://www.certum.eu/) | ~€30 / year | needs proof the project is OSS (public repo is enough); PFX + password, so it works with `build.py` |
| any commercial CA (Sectigo, DigiCert, …) | €200–400 / year | since June 2023 the key must live in hardware or a cloud HSM, which complicates local builds |

For a hobby mod distributed on a mod site, Certum is the pragmatic choice: a plain PFX
file works with the command below. SignPath is cheaper (free) but moves signing into a
workflow you do not control.

## Sign a build

```powershell
# one-time: export the certificate your CA gave you as a PFX with a password
# (Certum sends a PFX; if you got a .cer, you cannot sign with it — you need the key)

$env:WAYPOINT_SIGN_PASSWORD = "the pfx password"
python build.py --clean --sign-pfx "C:\path\to\waypoint.pfx"
```

`build.py` signs `dist/Waypoint/Waypoint.exe` **before** writing the zip (so the archive
contains the signed bytes), timestamps the signature, and stops if the status is not a
real signature. The password is read from the environment, never from the command line.

Check the result:

```powershell
Get-AuthenticodeSignature dist\Waypoint\Waypoint.exe | Format-List Status, SignerCertificate
```

`Valid` is what you want. `UnknownError` with a signer present means the certificate
chain is not trusted on this machine (typically a self-signed test certificate);
`NotSigned` means nothing happened.

## Sign in GitHub Actions (recommended)

Once you have a PFX, store it as a secret so CI releases are signed automatically:

```powershell
# base64 the pfx (one line, no wrapping)
[Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\path\to\waypoint.pfx")) |
  Set-Clipboard
```

Then, in the repository settings → *Secrets and variables* → *Actions*, add:

| secret | value |
|---|---|
| `SIGN_PFX_BASE64` | the base64 string above |
| `SIGN_PFX_PASSWORD` | the PFX password |

The workflow checks for `SIGN_PFX_BASE64`; when it is present it writes the file,
builds with `--sign-pfx`, and deletes the PFX. Without the secret, releases are built
unsigned exactly as before.

## Testing the plumbing without a certificate

A self-signed certificate is enough to prove that signing works end to end:

```powershell
$cert = New-SelfSignedCertificate -Type CodeSigningCert `
  -Subject "CN=Waypoint plumbing test" -CertStoreLocation Cert:\CurrentUser\My `
  -KeyUsage DigitalSignature -NotAfter (Get-Date).AddDays(7)
$pw = ConvertTo-SecureString -String "test" -AsPlainText -Force
Export-PfxCertificate -Cert $cert -FilePath "$env:TEMP\waypoint-test.pfx" -Password $pw
$env:WAYPOINT_SIGN_PASSWORD = "test"
python build.py --no-zip --sign-pfx "$env:TEMP\waypoint-test.pfx"
```

The status will read `UnknownError` (untrusted root) — expected, and the reason a
self-signed build must never be published.

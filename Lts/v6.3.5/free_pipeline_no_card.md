# Free, no-card pipeline: hosting + building + signing

Short version: GitHub Releases replaces R2 (genuinely free, no card, ever). Real
Authenticode signing has no free/no-card option — nothing does, since every CA and every
cloud signing service wants a card on file even at $0 charged. Here's the best
zero-cost stand-in for now, plus what to switch to the moment you can use a card.

## 1. Hosting: GitHub Releases instead of R2

No card, ever — for public repos. 2GB per file (official limit), no bandwidth limit.
Bonus: `github.com` / `objects.githubusercontent.com` is almost never blocked by
school content filters the way generic cloud-storage domains can be — it's one of the
most widely allowlisted developer domains there is.

Setup:
1. Create a **separate public repo** just for releases (e.g. `obylon-releases`) — keep
   your actual 5,800-line agent source in a private repo. The releases repo holds
   nothing but built binaries and checksums.
2. Upload via GitHub CLI (handles large files better than the web UI):
   ```
   gh release create v6.3.5 dist/obylon.exe dist/obylon.exe.sha256 --repo yourorg/obylon-releases --title "6.3.5"
   ```
3. Download URL for the MSI:
   `https://github.com/yourorg/obylon-releases/releases/download/v6.3.5/obylon.exe`
   — this 302-redirects to a signed CDN URL; `Invoke-WebRequest` follows redirects
   automatically, so nothing special needed on the install side.

Only real downside: release assets on a public repo are, well, public — anyone can grab
and inspect `obylon.exe` if they know to look. That's not really a new exposure though
(anyone deploying it can already extract it during install), and you need the checksum
public anyway for IT to verify it.

## 2. Building the exe for free — GitHub Actions (no Windows box, no card)

If you don't have a Windows machine to build on, GitHub Actions gives you one for free:
`windows-latest` runners are free and unlimited-minutes on public repos, no card
required. This also means "compile the exe" becomes "push a tag" from here on.

```yaml
# .github/workflows/release.yml (in your PRIVATE source repo)
name: Build and release agent
on:
  push:
    tags: ['v*']

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install deps
        run: |
          pip install -r requirements.txt
          pip install pyinstaller

      - name: Build
        run: pyinstaller obylon.spec

      - name: Self-sign (optional — see section 3)
        if: env.CODESIGN_PFX_BASE64 != ''
        shell: pwsh
        env:
          CODESIGN_PFX_BASE64: ${{ secrets.CODESIGN_PFX_BASE64 }}
          CODESIGN_PFX_PASSWORD: ${{ secrets.CODESIGN_PFX_PASSWORD }}
        run: |
          $bytes = [Convert]::FromBase64String($env:CODESIGN_PFX_BASE64)
          $pfxPath = "$env:RUNNER_TEMP\codesign.pfx"
          [IO.File]::WriteAllBytes($pfxPath, $bytes)
          $signtool = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Recurse -Filter signtool.exe |
            Where-Object { $_.FullName -match 'x64' } | Select-Object -First 1 -ExpandProperty FullName
          & $signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f $pfxPath /p $env:CODESIGN_PFX_PASSWORD dist\obylon.exe

      - name: Hash
        shell: pwsh
        run: |
          $hash = (Get-FileHash dist\obylon.exe -Algorithm SHA256).Hash
          Set-Content dist\obylon.exe.sha256 $hash

      - name: Publish release
        env:
          GH_TOKEN: ${{ secrets.RELEASES_REPO_TOKEN }}
        run: gh release create ${{ github.ref_name }} dist/obylon.exe dist/obylon.exe.sha256 --repo yourorg/obylon-releases --title ${{ github.ref_name }}
```

Notes:
- `RELEASES_REPO_TOKEN` needs to be a fine-grained personal access token with write
  access to the separate `obylon-releases` repo (the default `GITHUB_TOKEN` only has
  permission inside the repo the workflow runs in). Generating a PAT doesn't need a
  card either.
- The signing step just no-ops if you haven't added the secrets yet — safe to commit
  now, before you have a cert.
- `signtool.exe`'s path varies by SDK version installed on the runner image; the
  `Get-ChildItem -Recurse` lookup above finds it without hardcoding a version.

## 3. Signing for free — what's actually possible

Straight answer: there is no free, no-card path to a real Authenticode-trusted
signature. Every CA charges, and Microsoft Trusted Signing (the cheap ~$10/mo Azure
option) still requires a card on the Azure account even to try it. That's not
optional anywhere I've found — worth confirming yourself if it matters, since terms
change, but plan around it not existing for now.

What you *can* do for $0 today, given you're selling directly to specific schools
rather than shipping to the anonymous public — self-sign, and hand your public
certificate directly to each district's IT so they explicitly trust it. This is a
real, valid trust mechanism (not a workaround) for exactly your situation: a small
number of known B2B customers who are already doing manual exclusion/vault-level trust
steps anyway.

**One-time, on any Windows machine (not in CI):**
```powershell
$cert = New-SelfSignedCertificate -Type CodeSigning -Subject "CN=Your Company Name" `
  -KeyUsage DigitalSignature -FriendlyName "Obylon Code Signing" `
  -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(5)

$pwd = ConvertTo-SecureString -String "choose-a-strong-password" -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath obylon-codesign.pfx -Password $pwd
Export-Certificate -Cert $cert -FilePath obylon-codesign.cer   # public half — this is what you send to districts
```

Base64-encode the `.pfx` and store it (plus the password) as GitHub Actions secrets
(`CODESIGN_PFX_BASE64`, `CODESIGN_PFX_PASSWORD`) so CI can sign every release with the
*same* certificate — reusing one certificate matters here, since a district that
trusts a specific cert needs every release to be signed by that same cert, not a fresh
one each time.

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("obylon-codesign.pfx")) | Set-Clipboard
```

Send districts the `.cer` file (never the `.pfx` — that has your private key) along
with an import command for their IT to run once:
```powershell
Import-Certificate -FilePath obylon-codesign.cer -CertStoreLocation Cert:\LocalMachine\TrustedPublisher
```
Once that's in their Trusted Publisher store, Windows treats `obylon.exe` as coming
from a trusted, known publisher on their fleet specifically — same practical outcome as
a paid cert, scoped to districts who've explicitly opted in, for $0.

This doesn't move the needle on Defender/SmartScreen for machines that haven't done
that import (self-signed certs get essentially zero automatic reputation), so keep
doing the other free things in parallel: submit to
https://www.microsoft.com/wdsi/filesubmission once you have a stable signed build, and
lean on the checksum verification already in the installer. When you do get paid, a
budget OV certificate (roughly $70–130/year from providers like Certum or SSL.com,
well under EV pricing) is the first infrastructure purchase I'd make — it's the one
thing on this list that actually moves automatic AV/SmartScreen behavior instead of
just giving specific districts a way to opt in.

## 4. Updated MSI download step

```xml
<?define AgentDownloadUrl = "https://github.com/yourorg/obylon-releases/releases/download/v6.3.5/obylon.exe" ?>
<?define AgentHashUrl = "https://github.com/yourorg/obylon-releases/releases/download/v6.3.5/obylon.exe.sha256" ?>

<CustomAction Id="DownloadAgent"
              Directory="INSTALLFOLDER"
              ExeCommand="powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command &quot;$ErrorActionPreference='Stop'; $dest='[INSTALLFOLDER]obylon.exe'; Invoke-WebRequest -Uri '$(var.AgentDownloadUrl)' -OutFile $dest -UseBasicParsing; $expected=(Invoke-WebRequest -Uri '$(var.AgentHashUrl)' -UseBasicParsing).Content.Trim(); $actual=(Get-FileHash -Path $dest -Algorithm SHA256).Hash; if ($actual -ne $expected) { Remove-Item $dest -Force; throw \"Checksum mismatch: expected $expected, got $actual\" }&quot;"
              Execute="deferred"
              Impersonate="no"
              Return="check" />
```

This fetches the checksum file at install time instead of baking the hash into the
MSI, which means shipping a new agent build doesn't require rebuilding and
redistributing the MSI to every school — just push a new tag. Trade-off worth knowing:
since the hash file comes from the same release as the exe, this protects against
transit corruption/tampering (network issues, a MITM on an untrusted network) but not
against someone fully compromising your GitHub release itself. If you want protection
against that too, go back to pinning the hash into the MSI at build time (from the
previous doc) — more secure, more friction on every agent update. Given where you are
right now, I'd take the friction-free version and revisit once agent updates and MSI
updates are less tightly coupled to each other.

# Code Signing with Windows SignTool

## Overview

Windows `signtool.exe` can sign your installer to eliminate security warnings, but **requires a paid code signing certificate** ($200-500/year from DigiCert, Sectigo, etc.).

## Prerequisites

### 1. Get a Code Signing Certificate

**Commercial Certificates:**
- **DigiCert** (~$474/year) - Most trusted, fastest issuance
- **Sectigo (Comodo)** (~$199/year) - Good value
- **SSL.com** (~$199/year) - Budget option

**Process (1-5 business days):**
1. Purchase certificate from provider
2. Verify your identity (business documents or personal ID)
3. Receive certificate file (`.pfx` or `.p12` format)
4. Install certificate or keep file + password

### 2. Install Windows SDK

SignTool is included in Windows SDK (free):

**Download:** https://developer.microsoft.com/en-us/windows/downloads/windows-sdk/

**Typical paths after install:**
- Windows 10 SDK: `C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe`
- Windows 11 SDK: `C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe`

**Verify installation:**
```powershell
# Find signtool
where.exe signtool

# Or add to PATH
$env:PATH += ";C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64"
```

## Signing Methods

### Method 1: Sign from Installed Certificate (Windows Certificate Store)

**1. Install certificate to Windows:**
```powershell
# Double-click .pfx file and follow wizard, or:
certutil -user -p PASSWORD -importPFX certificate.pfx
```

**2. Find certificate thumbprint:**
```powershell
# List all code signing certificates
Get-ChildItem -Path Cert:\CurrentUser\My -CodeSigningCert

# Output shows Subject and Thumbprint
```

**3. Sign with signtool:**
```powershell
signtool sign /a /t http://timestamp.digicert.com /fd SHA256 /d "PFR Sentinel" /du "https://github.com/YOUR_USERNAME/PFRSentinel" "installer\dist\PFR Sentinel-3.2.0-setup.exe"
```

**Parameters:**
- `/a` - Auto-select best certificate
- `/t URL` - Timestamp server (proves signing date)
- `/fd SHA256` - Use SHA256 digest algorithm
- `/d "Description"` - Application description
- `/du URL` - Project URL (shows in certificate details)

### Method 2: Sign from PFX File

**If you have the .pfx file and password:**

```powershell
signtool sign /f "C:\path\to\certificate.pfx" /p "PASSWORD" /t http://timestamp.digicert.com /fd SHA256 /d "PFR Sentinel" /du "https://github.com/YOUR_USERNAME/PFRSentinel" "installer\dist\PFR Sentinel-3.2.0-setup.exe"
```

**Parameters:**
- `/f FILE` - Certificate file path
- `/p PASSWORD` - Certificate password

### Method 3: Sign with Hardware Token (USB Key)

**For EV (Extended Validation) certificates on USB token:**

```powershell
# List available tokens
certutil -csp "eToken Base Cryptographic Provider" -key

# Sign using token
signtool sign /csp "eToken Base Cryptographic Provider" /k "[KEY_CONTAINER_NAME]" /t http://timestamp.digicert.com /fd SHA256 /d "PFR Sentinel" "installer\dist\PFR Sentinel-3.2.0-setup.exe"
```

## Timestamp Servers

**Always use a timestamp server** - allows signatures to remain valid even after certificate expires.

**Recommended servers:**
- DigiCert: `http://timestamp.digicert.com`
- Sectigo: `http://timestamp.sectigo.com`
- GlobalSign: `http://timestamp.globalsign.com`

## Automated Build Script Integration

Update `build_sentinel_installer.bat` to optionally sign:

```batch
REM Step 3: Sign installer (if certificate available)
echo.
echo [3/4] Checking for code signing certificate...

REM Check for certificate thumbprint in environment
if defined CODE_SIGNING_THUMBPRINT (
    echo Found certificate, signing installer...
    signtool sign /sha1 %CODE_SIGNING_THUMBPRINT% /t http://timestamp.digicert.com /fd SHA256 /d "PFR Sentinel" "installer\dist\PFR Sentinel-%VERSION%-setup.exe"
    if %ERRORLEVEL% EQU 0 (
        echo ✓ Installer signed successfully!
    ) else (
        echo ⚠ Signing failed, continuing with unsigned installer
    )
) else (
    echo No certificate configured, skipping signing
    echo Set CODE_SIGNING_THUMBPRINT environment variable to enable
)
```

**Set certificate thumbprint once:**
```powershell
# Add to PowerShell profile or set per-session
$env:CODE_SIGNING_THUMBPRINT = "YOUR_CERT_THUMBPRINT_HERE"

# Or set permanently (user-level)
[Environment]::SetEnvironmentVariable("CODE_SIGNING_THUMBPRINT", "YOUR_THUMBPRINT", "User")
```

## Verification

**Verify signature after signing:**
```powershell
# Check signature
signtool verify /pa "installer\dist\PFR Sentinel-3.2.0-setup.exe"

# View certificate details
Get-AuthenticodeSignature "installer\dist\PFR Sentinel-3.2.0-setup.exe" | Format-List *
```

**Expected output:**
```
Successfully verified: PFR Sentinel-3.2.0-setup.exe
```

**Right-click EXE → Properties → Digital Signatures tab** should show your certificate.

## Cost-Benefit Analysis

### Benefits of Signing:
✅ No Windows SmartScreen warning  
✅ Builds user trust  
✅ Professional appearance  
✅ Protects against tampering  
✅ Better antivirus detection rates  

### Costs:
❌ $200-500/year recurring cost  
❌ Annual renewal required  
❌ Identity verification process  
❌ Time to obtain (1-5 days)  

### When to Sign:
- **Yes:** Commercial software, enterprise deployment, 1000+ users/month
- **No:** Personal projects, open source with source available, small user base
- **Maybe:** Growing open source project with 100-500 users

## Alternatives if You Can't Afford a Certificate

1. **Stay unsigned** - Document SmartScreen bypass in README
2. **VirusTotal scans** - Prove safety with public scan results (already implemented)
3. **Build reputation** - After ~100 clean downloads, SmartScreen warnings reduce
4. **Source availability** - Let users build from source (most trustworthy)
5. **Community vouching** - Get GitHub stars, user testimonials

## Common Issues

### "No certificates were found that met all the given criteria"
- Certificate not installed or expired
- Wrong thumbprint or certificate store
- Certificate missing code signing EKU (Extended Key Usage)

### "The timestamp signature and/or certificate could not be verified"
- Timestamp server down (try different server)
- Network firewall blocking HTTP requests
- Use `/tr` with HTTPS timestamp instead of `/t`

### "Access is denied"
- Certificate file is read-only
- Certificate password incorrect
- Need admin rights for certain certificate stores

## Security Best Practices

🔒 **Protect your certificate:**
- Store .pfx files encrypted
- Use strong passwords (20+ characters)
- Never commit certificates to git
- Consider hardware token (USB) for high-security

🔒 **Secure signing process:**
- Sign on air-gapped or secure build machine
- Verify signatures immediately after signing
- Keep certificate backups (encrypted)
- Revoke certificate immediately if compromised

## GitHub Actions Integration

**For CI/CD signing (requires certificate in GitHub Secrets):**

```yaml
- name: Sign installer
  if: env.CODE_SIGNING_PFX != ''
  shell: pwsh
  run: |
    $pfxPath = "certificate.pfx"
    [System.IO.File]::WriteAllBytes($pfxPath, [System.Convert]::FromBase64String($env:CODE_SIGNING_PFX))
    & signtool sign /f $pfxPath /p $env:CODE_SIGNING_PASSWORD /t http://timestamp.digicert.com /fd SHA256 /d "PFR Sentinel" "installer\dist\PFR Sentinel-${{ env.VERSION }}-setup.exe"
    Remove-Item $pfxPath
  env:
    CODE_SIGNING_PFX: ${{ secrets.CODE_SIGNING_PFX }}
    CODE_SIGNING_PASSWORD: ${{ secrets.CODE_SIGNING_PASSWORD }}
```

## Resources

- [Microsoft SignTool Documentation](https://docs.microsoft.com/en-us/windows/win32/seccrypto/signtool)
- [Code Signing Best Practices](https://docs.digicert.com/en/software-trust-manager/ci-cd-integrations/plugins/code-signing-best-practices.html)
- [Certificate Comparison](https://comodosslstore.com/code-signing/compare-prices)

---

**Current Status:** PFR Sentinel is **unsigned**. This is normal for open source projects. Users can verify safety via:
- [VirusTotal scan results](https://www.virustotal.com/gui/file/7c7f23993cf433fbfaf385f697fc50453ec9bbac10b5f21002549538055479cf)
- Source code review on GitHub
- Building from source using `build_sentinel_installer.bat`

# Code Signing for Windows Applications

## The "Unknown Publisher" Warning

When users download and run `ASIOverlayWatchDog.exe`, Windows will show a SmartScreen warning:

```
Windows protected your PC
Microsoft Defender SmartScreen prevented an unrecognized app from starting.
Running this app might put your PC at risk.

Publisher: Unknown publisher
```

This is **normal for unsigned executables** and does NOT mean the app is malicious. It's Windows' way of protecting users from potentially harmful software.

## Why This Happens

Windows SmartScreen checks for:
1. **Digital signature** - Proves the publisher's identity
2. **Reputation** - Tracks how many users have downloaded the file
3. **Certificate validity** - Ensures the signature is from a trusted authority

ASIOverlayWatchDog is **unsigned**, so Windows shows the warning.

## What Users Should Do

Users can safely bypass this warning:

1. Click **"More info"** link
2. Click **"Run anyway"** button
3. The application will start normally

Once enough users download and run the app without reporting issues, Windows SmartScreen will build a reputation and stop showing the warning (this takes weeks/months and many downloads).

## Code Signing Options

### Option 1: Accept the Warning (Current - FREE)
**Cost:** $0  
**Pros:**
- No cost
- No annual renewals
- Still fully functional

**Cons:**
- Users see warning on first run
- May reduce trust for some users
- Requires clicking "More info" → "Run anyway"

**Best for:** Open source projects, personal use, small user base

---

### Option 2: Get a Code Signing Certificate (EXPENSIVE)

**Cost:** $100-$500/year  
**Pros:**
- No SmartScreen warning
- Builds user trust
- Professional appearance
- Protects against tampering

**Cons:**
- Expensive recurring cost
- Requires identity verification
- Annual renewal required
- Takes time to obtain

**Providers:**
- **DigiCert** (~$474/year) - Most trusted
- **Sectigo (Comodo)** (~$199/year) - Good value
- **SSL.com** (~$199/year) - Affordable option

**Process:**
1. Purchase certificate from provider
2. Verify your identity (business or personal)
3. Receive certificate file (.pfx or .p12)
4. Sign executable with `signtool.exe`:
   ```powershell
   signtool sign /f certificate.pfx /p password /t http://timestamp.digicert.com ASIOverlayWatchDog.exe
   ```

**Best for:** Commercial software, large user base, professional deployments

---

### Option 3: Self-Signed Certificate (NOT RECOMMENDED)

**Cost:** $0  
**Effect:** **Makes warning worse** - Windows shows "Unknown publisher" AND "Untrusted certificate"

Self-signing doesn't help because Windows only trusts certificates from recognized Certificate Authorities (CAs). Users would need to manually import your certificate to their Trusted Publishers store.

**Don't do this** - it's more work for users than just clicking "Run anyway."

---

## Recommendation for ASIOverlayWatchDog

**Stay unsigned (Option 1)** because:

1. **Cost:** $200-500/year is significant for a free open-source project
2. **User base:** Astrophotography enthusiasts are tech-savvy and understand SmartScreen warnings
3. **Distribution:** GitHub releases build reputation over time
4. **Alternatives:** Clear documentation helps users understand the warning

### How to Minimize User Friction

1. **README Warning:**
   ```markdown
   **Windows Security Warning:** When you first run ASIOverlayWatchDog.exe,
   Windows may show a SmartScreen warning. This is normal for unsigned software.
   Click "More info" → "Run anyway" to proceed.
   ```

2. **GitHub Releases:** Use official GitHub releases - users trust downloads from github.com

3. **Source Code:** Provide source code so advanced users can build it themselves

4. **Virus Scan Results:** Upload to VirusTotal and link the clean scan results

5. **Video Tutorial:** Show the SmartScreen bypass process in a setup video

---

## Future Consideration

If the project grows to:
- 1000+ downloads/month
- Commercial support
- Paid version
- Business partnerships

Then code signing becomes worth the investment. Until then, the free option is perfectly acceptable for an open-source astrophotography tool.

---

## Resources

- [Microsoft Code Signing Overview](https://docs.microsoft.com/en-us/windows/win32/seccrypto/cryptography-tools)
- [DigiCert Code Signing](https://www.digicert.com/signing/code-signing-certificates)
- [Sectigo Code Signing](https://sectigo.com/ssl-certificates-tls/code-signing)
- [VirusTotal](https://www.virustotal.com/) - Free malware scanning service

---

**Current Status:** ASIOverlayWatchDog is **unsigned** and will show SmartScreen warning. This is normal and safe for open-source software.

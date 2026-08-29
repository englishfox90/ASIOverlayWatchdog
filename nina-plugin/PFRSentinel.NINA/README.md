# PFR Sentinel - N.I.N.A. plugin

Scaffold for item 1a of `docs/NINA_INTEGRATION_PLAN.md`.

Build: `dotnet build -c Release` (requires the .NET 8 SDK).
The PostBuild target copies the DLL to `%LOCALAPPDATA%\NINA\Plugins\3.0.0\PFRSentinel.NINA\`.
Close N.I.N.A. before rebuilding - it locks loaded plugin assemblies.

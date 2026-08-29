using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;

// [MANDATORY] Unique identifier of the plugin. NEVER change this after first release -
// NINA keys per-plugin profile settings off it (PluginOptionsAccessor).
[assembly: Guid("e2e840b9-b5e2-4f67-8699-0173b5f9dc0a")]

// [MANDATORY] Assembly versioning - increment for each release build.
[assembly: AssemblyVersion("1.1.0.0")]
[assembly: AssemblyFileVersion("1.1.0.0")]

// [MANDATORY] AssemblyTitle is the name NINA shows in the plugin list, and is also the
// prefix of the options DataTemplate key ("PFR Sentinel_Options" in Options.xaml).
[assembly: AssemblyTitle("PFR Sentinel")]
[assembly: AssemblyDescription("Live pier-camera frame, health, and capture start/stop for PFR Sentinel.")]

[assembly: AssemblyCompany("Paul Fox-Reeks")]
[assembly: AssemblyProduct("PFR Sentinel")]
[assembly: AssemblyCopyright("Copyright © 2026 Paul Fox-Reeks")]

// Must be <= the running NINA version (3.2.0.9001 here) or the plugin is not loaded.
[assembly: AssemblyMetadata("MinimumApplicationVersion", "3.0.0.2017")]

[assembly: AssemblyMetadata("License", "MPL-2.0")]
[assembly: AssemblyMetadata("LicenseURL", "https://www.mozilla.org/en-US/MPL/2.0/")]
[assembly: AssemblyMetadata("Repository", "https://github.com/englishfox90/PFRSentinel")]

[assembly: AssemblyMetadata("Homepage", "https://github.com/englishfox90/PFRSentinel")]
[assembly: AssemblyMetadata("Tags", "Sentinel,All Sky,Monitoring,Capture Control")]
// Points at GitHub Releases, which exist and are already maintained. The
// template default (/CHANGELOG.md) 404s: no such file in the repo, and the
// path is missing /blob/main/ anyway. NINA renders this as a live link in
// the plugin list, so a dead one is user-visible.
[assembly: AssemblyMetadata("ChangelogURL", "https://github.com/englishfox90/PFRSentinel/releases")]
// The icon NINA shows beside the plugin name. IPluginManifest has no icon
// property and plugins ship no image files — every icon-bearing plugin
// (Connector, Livestack, Sequencer+) points this at a raw GitHub URL, so
// NINA fetches it over the network. On an isolated observatory PC with no
// internet it falls back to the default puzzle piece; nothing else breaks.
[assembly: AssemblyMetadata("FeaturedImageURL", "https://raw.githubusercontent.com/englishfox90/PFRSentinel/main/assets/app_icon.png")]
[assembly: AssemblyMetadata("ScreenshotURL", "")]
[assembly: AssemblyMetadata("AltScreenshotURL", "")]
[assembly: AssemblyMetadata("LongDescription", @"Surfaces the PFR Sentinel pier camera inside N.I.N.A.: a live frame with a staleness indicator, the Sentinel health line, and Start/Stop capture driven by Sentinel's local capture-control HTTP API.")]

[assembly: ComVisible(false)]
[assembly: AssemblyConfiguration("")]
[assembly: AssemblyTrademark("")]
[assembly: AssemblyCulture("")]

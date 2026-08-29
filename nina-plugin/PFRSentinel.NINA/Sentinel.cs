using NINA.Core.Utility;
using NINA.Plugin;
using NINA.Plugin.Interfaces;
using NINA.Profile;
using NINA.Profile.Interfaces;
using System;
using System.ComponentModel;
using System.ComponentModel.Composition;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using Settings = PFRSentinel.NINA.Properties.Settings;

namespace PFRSentinel.NINA {

    /// <summary>
    /// Exports IPluginManifest. PluginBase populates the manifest metadata from the
    /// AssemblyInfo attributes, so the plugin list entry is driven entirely by
    /// Properties/AssemblyInfo.cs.
    ///
    /// An instance of this class is the DataContext of the plugin's options page. The
    /// DataTemplate for that page must be keyed "&lt;AssemblyTitle&gt;_Options" -
    /// "PFR Sentinel_Options" - see Options.xaml.
    /// </summary>
    [Export(typeof(IPluginManifest))]
    public class Sentinel : PluginBase, INotifyPropertyChanged {
        private readonly IPluginOptionsAccessor pluginSettings;
        private readonly IProfileService profileService;

        [ImportingConstructor]
        public Sentinel(IProfileService profileService) {
            if (Settings.Default.UpdateSettings) {
                Settings.Default.Upgrade();
                Settings.Default.UpdateSettings = false;
                CoreUtil.SaveSettings(Settings.Default);
            }

            // Identifier comes from the assembly [Guid]. Profile-scoped plugin settings
            // are keyed off it, which is why that GUID must never change. Built through
            // the shared helper so the dockable panel, which has to reach the same
            // bucket from a separate MEF export, cannot end up reading a different one.
            this.pluginSettings = SentinelPluginOptions.Accessor(profileService);
            this.profileService = profileService;
            profileService.ProfileChanged += ProfileService_ProfileChanged;
        }

        public override Task Teardown() {
            // Unhook or the plugin instance is never collected.
            profileService.ProfileChanged -= ProfileService_ProfileChanged;
            return base.Teardown();
        }

        private void ProfileService_ProfileChanged(object sender, EventArgs e) {
            RaisePropertyChanged(nameof(BaseUrlOverride));
        }

        /// <summary>
        /// Where the dockable panel looks for Sentinel. Empty means "discover host and
        /// port from Sentinel's own config.json", which is what a local install wants.
        /// </summary>
        /// <remarks>
        /// <para>
        /// The panel re-reads this on every poll, so an edit takes effect within a few
        /// seconds without restarting NINA. A value that is not a valid http(s) address
        /// is reported by the panel as a configuration problem naming the bad value; it
        /// is never sent to the network.
        /// </para>
        /// <para>
        /// This overrides the address only. The control token still comes from the local
        /// config.json, so pointing at Sentinel on another machine gives you its frames
        /// and health but not Start/Stop, unless that machine's token happens to match.
        /// </para>
        /// </remarks>
        public string BaseUrlOverride {
            get => pluginSettings.GetValueString(SentinelPluginOptions.BaseUrlOverrideKey, string.Empty);
            set {
                pluginSettings.SetValueString(SentinelPluginOptions.BaseUrlOverrideKey, value ?? string.Empty);
                RaisePropertyChanged();
            }
        }

        public event PropertyChangedEventHandler PropertyChanged;

        protected void RaisePropertyChanged([CallerMemberName] string propertyName = null) {
            this.PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        }
    }
}

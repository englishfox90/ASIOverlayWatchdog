#nullable enable
using Newtonsoft.Json;
using NINA.Core.Model;
using NINA.Core.Utility;
using NINA.Sequencer.SequenceItem;
using NINA.Sequencer.Validations;
using NINA.Profile.Interfaces;
using PFRSentinel.Nina.Client;
using System;
using System.Collections.Generic;
using System.ComponentModel.Composition;
using System.Threading;
using System.Threading.Tasks;

namespace PFRSentinel.NINA.SentinelSequenceItems {

    /// <summary>
    /// Stops PFR Sentinel's capture loop and blocks until capture has genuinely
    /// stopped.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Namespace and type name are load-bearing forever: a saved sequence serialises
    /// the fully qualified type name, so renaming this after a release breaks every
    /// sequence that used it.
    /// </para>
    /// <para>
    /// Stopping is a pause, not a shutdown. Sentinel keeps running so the matching
    /// Start at the next dusk still has something to reach.
    /// </para>
    /// </remarks>
    [ExportMetadata("Name", "Stop Sentinel Capture")]
    [ExportMetadata("Description", "Stops PFR Sentinel capture and waits until it has actually stopped before the sequence continues. Safe to re-run: an already-stopped capture succeeds without changing anything.")]
    [ExportMetadata("Icon", "PFRSentinel_SVG")]
    [ExportMetadata("Category", "PFR Sentinel")]
    [Export(typeof(ISequenceItem))]
    [JsonObject(MemberSerialization.OptIn)]
    public class StopSentinelCapture : SequenceItem, IValidatable {

        private readonly IProfileService? profileService;
        private readonly IPluginOptionsAccessor? options;

        private IList<string> issues = new List<string>();
        private int timeoutSeconds = SentinelCommandOptions.DefaultTimeoutSeconds;

        /// <summary>Constructed by MEF for the instruction factory.</summary>
        /// <param name="profileService">
        /// Injected so this instruction reads the same profile-scoped base URL override
        /// the dockable panel does. Without it the two halves of the plugin could end up
        /// talking to different Sentinels.
        /// </param>
        [ImportingConstructor]
        public StopSentinelCapture(IProfileService profileService) {
            this.profileService = profileService;
            options = profileService is null ? null : SentinelPluginOptions.Accessor(profileService);
        }

        /// <summary>Copy constructor backing <see cref="Clone"/>.</summary>
        /// <remarks>
        /// The profile service is threaded through rather than re-imported: a clone is
        /// built by the sequencer, not by MEF, so nothing else would supply it and the
        /// copy would silently stop honouring the override.
        /// </remarks>
        public StopSentinelCapture(StopSentinelCapture copyMe) : this(copyMe.profileService!) {
            CopyMetaData(copyMe);
        }

        /// <summary>
        /// How long Sentinel waits for capture to reach the stopped state, in seconds.
        /// </summary>
        /// <remarks>
        /// Clamped to the server bounds (<c>api_control.TIMEOUT_MIN</c> /
        /// <c>TIMEOUT_MAX</c>) rather than validated, so a hand-edited sequence file
        /// cannot turn into an HTTP 400 in the middle of the night.
        /// </remarks>
        [JsonProperty]
        public int TimeoutSeconds {
            get => timeoutSeconds;
            set {
                timeoutSeconds = Math.Clamp(
                    value,
                    SentinelCommandOptions.MinTimeoutSeconds,
                    SentinelCommandOptions.MaxTimeoutSeconds);
                RaisePropertyChanged(nameof(TimeoutSeconds));
            }
        }

        /// <summary>Validation problems shown against this instruction.</summary>
        /// <remarks>
        /// A notifying setter rather than a plain auto-property: NINA re-runs
        /// <see cref="Validate"/> from a background timer, so without the notification
        /// an issue that appears - or clears - after the sequence was built would never
        /// reach the UI.
        /// </remarks>
        public IList<string> Issues {
            get => issues;
            set {
                issues = value;
                RaisePropertyChanged(nameof(Issues));
            }
        }

        /// <summary>
        /// Reports whether Sentinel could accept this command right now.
        /// </summary>
        /// <remarks>
        /// <para>
        /// Returns from a cached snapshot and starts any refresh in the background, so
        /// it is a field read: no <c>.Result</c>, no <c>.Wait()</c>, nothing that can
        /// block NINA's validation timer or its UI.
        /// </para>
        /// <para>
        /// Before the first probe answers there are no issues. "Not asked yet" is not
        /// evidence that Sentinel is down, and NINA revalidates within seconds.
        /// </para>
        /// </remarks>
        public bool Validate() {
            SentinelSequenceLink.Instance.ApplyEndpointOverride(
                SentinelPluginOptions.ReadBaseUrlOverride(options));

            SentinelReadiness readiness = SentinelSequenceLink.Instance.GetReadiness();
            Issues = new List<string>(readiness.Issues);
            return Issues.Count == 0;
        }

        /// <summary>
        /// Issues the stop command and waits for capture to reach the stopped state.
        /// </summary>
        /// <remarks>
        /// <para>
        /// <b>Cancellation abandons the request and compensates for nothing.</b>
        /// Sentinel hands the command to the thread that owns capture <em>before</em>
        /// it begins waiting for the target state, so by the time the socket can be
        /// aborted capture has already been told to stop; cancelling discards the
        /// confirmation, not the command.
        /// <see cref="SentinelCancellation.AbandonRequest"/> is chosen over
        /// <see cref="SentinelCancellation.CompleteRequest"/> for the same reason as on
        /// Start: waiting the server out would only reveal the true final state, and
        /// the only use for that is issuing a compensating command, which this
        /// instruction deliberately does not do. The asymmetry is worth naming - a
        /// cancelled Stop that took effect anyway is the harmless direction, and a
        /// re-run Stop is a no-op, so an operator who wants certainty can simply run
        /// this instruction again.
        /// </para>
        /// <para>
        /// Any 2xx is success, including <c>already_stopped</c> - an aborting sequence
        /// may legitimately fire Stop twice, and neither call may fail the sequence.
        /// </para>
        /// </remarks>
        public override async Task Execute(IProgress<ApplicationStatus> progress, CancellationToken token) {
            progress?.Report(new ApplicationStatus { Status = "Stopping PFR Sentinel capture..." });

            // Re-read here as well as in Validate: an operator can correct the base URL
            // after validation has run, and a step that ignored the fix until NINA
            // restarted would be baffling.
            SentinelSequenceLink.Instance.ApplyEndpointOverride(
                SentinelPluginOptions.ReadBaseUrlOverride(options));

            try {
                SentinelCommandOutcome outcome = await SentinelSequenceLink.Instance
                    .SendAsync(start: false, TimeoutSeconds, token).ConfigureAwait(false);

                if (!outcome.Succeeded) {
                    Logger.Error($"PFR Sentinel: stop failed - {outcome.Message}");
                    throw new SequenceEntityFailedException(outcome.Message);
                }

                Logger.Info($"PFR Sentinel: {outcome.Message}");
                progress?.Report(new ApplicationStatus { Status = outcome.Message });
            } catch (SentinelCommandAbandonedException ex) {
                Logger.Warning($"PFR Sentinel: {ex.Message} Capture was NOT restarted to compensate.");

                // Rethrown as a plain cancellation carrying the sequencer token, which
                // is what NINA unwinds cleanly on.
                token.ThrowIfCancellationRequested();
                throw;
            }
        }

        /// <summary>
        /// Clones this instruction, carrying every <c>[JsonProperty]</c>.
        /// </summary>
        /// <remarks>
        /// The sequencer clones from the factory on drop, so a missed property fails
        /// silently: the item works when first built and loses the value on
        /// save/reload.
        /// </remarks>
        public override object Clone() {
            return new StopSentinelCapture(this) {
                TimeoutSeconds = TimeoutSeconds
            };
        }

        /// <summary>Line written to the sequence log.</summary>
        public override string ToString() {
            return $"Category: {Category}, Item: {nameof(StopSentinelCapture)}, TimeoutSeconds: {TimeoutSeconds}";
        }
    }
}

#nullable enable
using NINA.Core.Utility;
using NINA.Equipment.Interfaces.ViewModel;
using NINA.Profile.Interfaces;
using NINA.WPF.Base.ViewModel;
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.Composition;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using RelayCommand = CommunityToolkit.Mvvm.Input.RelayCommand;

namespace PFRSentinel.NINA.SentinelDockables {

    /// <summary>
    /// The imaging-tab panel: Sentinel's latest frame, its health, and Start/Stop.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Three things must agree exactly or MEF drops the export and the panel silently
    /// never appears in the panel picker:
    /// </para>
    /// <list type="number">
    /// <item><description>the pack URI below → <c>AssemblyName;component/&lt;folder&gt;/&lt;file&gt;.xaml</c></description></item>
    /// <item><description>the ImageGeometry key → the <c>GeometryGroup</c> x:Key in that dictionary</description></item>
    /// <item><description>the DataTemplate x:Key → this type's full name + <c>_Dockable</c></description></item>
    /// </list>
    /// <para>
    /// All network work lives in <see cref="SentinelPoller"/>; this class only marshals
    /// its snapshots onto the UI thread and formats them.
    /// </para>
    /// </remarks>
    [Export(typeof(IDockableVM))]
    public partial class SentinelDockable : DockableVM, IDisposable {

        private readonly SentinelPoller poller;
        private readonly Dispatcher? dispatcher;
        private readonly CancellationTokenSource commandLifetime = new();
        private readonly IPluginOptionsAccessor pluginSettings;

        private SentinelControlState lastControl = SentinelControlState.Unknown;
        private SentinelLinkState lastLink = SentinelLinkState.Connecting;
        private string controlDetail = string.Empty;
        private bool controlAvailable;
        private bool commandInFlight;
        private bool disposed;

        /// <summary>Constructed by MEF, once, when NINA builds its dockable list.</summary>
        [ImportingConstructor]
        public SentinelDockable(IProfileService profileService) : base(profileService) {
            var dict = new ResourceDictionary {
                Source = new Uri(
                    "PFRSentinel.NINA;component/SentinelDockables/SentinelDockableTemplates.xaml",
                    UriKind.RelativeOrAbsolute)
            };
            ImageGeometry = (GeometryGroup)dict["PFRSentinel_DockableSVG"];
            ImageGeometry.Freeze();

            Title = "PFR Sentinel";

            // Dispatcher.CurrentDispatcher would *create* one for whatever thread MEF
            // used, and a dispatcher with no message pump swallows every update
            // silently. Fall back to null, which makes RunOnUi apply inline.
            dispatcher = Application.Current?.Dispatcher ?? Dispatcher.FromThread(Thread.CurrentThread);

            StartCommand = new RelayCommand(() => IssueCommand(start: true));
            StopCommand = new RelayCommand(() => IssueCommand(start: false));
            ReconnectCommand = new RelayCommand(Reconnect);

            pluginSettings = SentinelPluginOptions.Accessor(profileService);

            // Read through a callback so the poller stays free of NINA types and an edit
            // on the options page lands on the next poll without a restart.
            poller = new SentinelPoller(
                baseUrlOverrideSource: () => SentinelPluginOptions.ReadBaseUrlOverride(pluginSettings));
            poller.SnapshotReady += OnSnapshotReady;

            // DockableVM's constructor has already set IsVisible; mirror it before the
            // loop starts so a panel that opens hidden never issues a request.
            poller.Visible = IsVisible;
            PropertyChanged += OnSelfPropertyChanged;

            poller.Start();
        }

        /// <summary>Starts capture in Sentinel's configured mode.</summary>
        public ICommand StartCommand { get; }

        /// <summary>Stops capture.</summary>
        public ICommand StopCommand { get; }

        /// <summary>Re-reads Sentinel's config.json and polls immediately.</summary>
        public ICommand ReconnectCommand { get; }

        /// <summary>Stops the poll loop and releases the HTTP client.</summary>
        public void Dispose() {
            if (disposed) {
                return;
            }

            disposed = true;

            PropertyChanged -= OnSelfPropertyChanged;
            poller.SnapshotReady -= OnSnapshotReady;

            try {
                commandLifetime.Cancel();
            } catch (ObjectDisposedException) {
            }

            poller.Dispose();
            commandLifetime.Dispose();
            GC.SuppressFinalize(this);
        }

        private void OnSelfPropertyChanged(object? sender, PropertyChangedEventArgs e) {
            // IsVisible is not virtual on DockableVM, so there is nothing to override;
            // its setter does raise PropertyChanged, which is enough to gate the poll.
            if (e.PropertyName is null || e.PropertyName.Length == 0 || e.PropertyName == nameof(IsVisible)) {
                poller.Visible = IsVisible;
            }
        }

        private void OnSnapshotReady(SentinelPanelSnapshot snapshot) => RunOnUi(() => Apply(snapshot));

        private void Apply(SentinelPanelSnapshot snapshot) {
            bool hasFrame = snapshot.Frame is not null;

            Frame = snapshot.Frame;
            FrameVisibility = hasFrame ? Visibility.Visible : Visibility.Collapsed;
            PlaceholderVisibility = hasFrame ? Visibility.Collapsed : Visibility.Visible;
            PlaceholderText = DescribeMissingFrame(snapshot);

            // Dimming is the point: an hours-old frame at full strength reads as live.
            FrameOpacity = snapshot.Stale ? 0.30 : 1.0;
            StaleVisibility = hasFrame && snapshot.Stale ? Visibility.Visible : Visibility.Collapsed;
            FrameStatusText = DescribeFrame(snapshot, hasFrame);
            FrameStatusBrush = snapshot.Stale ? WarnBrush : MutedBrush;

            HealthStatusText = SentinelPanelText.Health(snapshot.HealthStatus);
            HealthBrush = BrushForHealth(snapshot.HealthStatus);
            HealthReasons = snapshot.HealthReasons;
            HealthReasonsVisibility = snapshot.HealthReasons.Count > 0
                ? Visibility.Visible
                : Visibility.Collapsed;

            Statistics = SentinelStatistics.Build(snapshot);

            ApplyLinkNotice(snapshot);

            // An override is normal context, not an error — but it has to be visible, or
            // a stale one looks like Sentinel misbehaving rather than a setting.
            EndpointText = snapshot.EndpointIsOverride
                ? $"{snapshot.Endpoint}  ·  options override"
                : snapshot.Endpoint;
            EndpointBrush = snapshot.EndpointIsOverride ? WarnBrush : MutedBrush;

            lastControl = snapshot.Control;
            lastLink = snapshot.Link;
            controlAvailable = SentinelCommandAvailability.CanIssue(snapshot.Control);
            controlDetail = Without(Join(snapshot.ControlMessage, snapshot.ControlAdvice), LinkNoticeText);
            UpdateCommandAvailability();
        }

        /// <summary>
        /// Re-derives the button state and, whenever they are dead, the reason beside them.
        /// </summary>
        /// <remarks>
        /// The single place that writes <see cref="CanIssueCommands"/>, so the invariant
        /// "disabled implies a visible reason" cannot be broken by one caller forgetting
        /// to set the caption. Health is deliberately not an input — see
        /// <see cref="SentinelCommandAvailability"/>.
        /// </remarks>
        private void UpdateCommandAvailability() {
            CanIssueCommands = controlAvailable && !commandInFlight;

            if (CanIssueCommands) {
                CommandsDisabledVisibility = Visibility.Collapsed;
                CommandsDisabledText = string.Empty;
                return;
            }

            string reason = SentinelCommandAvailability.DescribeBlock(lastControl, lastLink, commandInFlight);
            CommandsDisabledText = commandInFlight ? reason : Join(reason, controlDetail);
            CommandsDisabledVisibility = Visibility.Visible;
        }

        private void ApplyLinkNotice(SentinelPanelSnapshot snapshot) {
            if (snapshot.Link is SentinelLinkState.Connected or SentinelLinkState.Connecting) {
                LinkNoticeVisibility = Visibility.Collapsed;
                LinkNoticeText = string.Empty;
                return;
            }

            LinkNoticeText = Join(snapshot.LinkMessage, snapshot.LinkAdvice);
            LinkNoticeBrush = snapshot.Link == SentinelLinkState.Unreachable ? ErrorBrush : WarnBrush;
            LinkNoticeVisibility = Visibility.Visible;
        }

        private static string DescribeMissingFrame(SentinelPanelSnapshot snapshot) => snapshot.Link switch {
            SentinelLinkState.Connecting => "Connecting to Sentinel…",
            SentinelLinkState.Connected when snapshot.NoImageYet =>
                "Sentinel is running but has not produced an image yet.",
            SentinelLinkState.Connected => "Waiting for the first frame…",
            _ => "Not connected to Sentinel.",
        };

        private static string DescribeFrame(SentinelPanelSnapshot snapshot, bool hasFrame) {
            if (!hasFrame) {
                return string.Empty;
            }

            string age = SentinelPanelText.Age(snapshot.AgeSeconds);
            string lead = snapshot.Stale
                ? $"STALE — last frame {age} old"
                : $"Last frame {age} old";

            return snapshot.ImageName.Length > 0 ? $"{lead}  ·  {snapshot.ImageName}" : lead;
        }

        private static Brush BrushForHealth(string status) => status switch {
            "ok" => OkBrush,
            "idle" => MutedBrush,
            "degraded" or "recovering" => WarnBrush,
            "error" => ErrorBrush,
            _ => MutedBrush,
        };

        /// <summary>Joins non-empty, non-repeated lines.</summary>
        /// <remarks>
        /// The client's message and its <c>OperatorAdvice</c> are sometimes the same
        /// sentence — a rejected token, for one — and printing it twice reads as two
        /// separate problems.
        /// </remarks>
        private static string Join(params string[] parts) {
            var lines = new List<string>(parts.Length);
            foreach (string part in parts) {
                if (!string.IsNullOrWhiteSpace(part) && !lines.Contains(part)) {
                    lines.Add(part);
                }
            }

            return string.Join(Environment.NewLine, lines);
        }

        /// <summary>Drops any line of <paramref name="text"/> already shown in <paramref name="shownElsewhere"/>.</summary>
        private static string Without(string text, string shownElsewhere) {
            if (shownElsewhere.Length == 0) {
                return text;
            }

            string[] already = shownElsewhere.Split(new[] { Environment.NewLine }, StringSplitOptions.None);
            string[] lines = text.Split(new[] { Environment.NewLine }, StringSplitOptions.None);
            return Join(Array.FindAll(lines, line => Array.IndexOf(already, line) < 0));
        }

        private void Reconnect() {
            CommandMessageVisibility = Visibility.Collapsed;
            CommandMessageText = string.Empty;
            poller.Reconnect();
        }

        private void IssueCommand(bool start) {
            if (commandInFlight || !controlAvailable || disposed) {
                return;
            }

            commandInFlight = true;
            UpdateCommandAvailability();
            CommandMessageText = start ? "Starting capture…" : "Stopping capture…";
            CommandMessageBrush = MutedBrush;
            CommandMessageVisibility = Visibility.Visible;

            // Fire and forget on purpose: the button must return control to the operator
            // immediately, and a wait:true command can hold the wire for up to 45s.
            _ = RunCommandAsync(start);
        }

        private async Task RunCommandAsync(bool start) {
            SentinelCommandOutcome outcome;

            try {
                outcome = await poller
                    .SendCommandAsync(start, commandLifetime.Token)
                    .ConfigureAwait(false);
            } catch (Exception ex) {
                // SendCommandAsync already absorbs everything; this only exists so a bug
                // there cannot surface as an unobserved task exception in NINA.
                Logger.Error(ex);
                outcome = new SentinelCommandOutcome {
                    Succeeded = false,
                    Message = $"The command failed unexpectedly ({ex.GetType().Name}).",
                };
            }

            RunOnUi(() => {
                commandInFlight = false;
                UpdateCommandAvailability();

                // Sentinel's own wording, verbatim: it is the only thing that names the
                // real cause, e.g. "No ZWO cameras detected. Check USB connections."
                CommandMessageText = Join(outcome.Message, outcome.Advice);
                CommandMessageBrush = outcome.Succeeded ? MutedBrush : ErrorBrush;
                CommandMessageVisibility = CommandMessageText.Length > 0
                    ? Visibility.Visible
                    : Visibility.Collapsed;
            });
        }

        private void RunOnUi(Action action) {
            Dispatcher? target = dispatcher;

            if (target is null || target.CheckAccess()) {
                Guarded(action);
                return;
            }

            try {
                target.BeginInvoke(new Action(() => Guarded(action)));
            } catch (Exception ex) {
                // The dispatcher is shutting down. Nothing left to update.
                Logger.Debug($"Sentinel panel could not marshal an update: {ex.GetType().Name}");
            }
        }

        private static void Guarded(Action action) {
            try {
                action();
            } catch (Exception ex) {
                // An exception thrown from a dispatcher callback tears down NINA's UI.
                Logger.Error(ex);
            }
        }
    }
}

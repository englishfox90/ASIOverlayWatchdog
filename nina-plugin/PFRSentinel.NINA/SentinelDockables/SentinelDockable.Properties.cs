#nullable enable
using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace PFRSentinel.NINA.SentinelDockables {

    /// <summary>
    /// The bindable surface of the panel.
    /// </summary>
    /// <remarks>
    /// <para>
    /// <see cref="Visibility"/> and <see cref="Brush"/> are exposed directly rather than
    /// derived in XAML through converters or <c>StaticResource</c> lookups. A missing
    /// resource key or converter is a load-time exception inside a DataTemplate, and the
    /// symptom is a panel that renders as nothing at all with no error the operator can
    /// see. Plain properties cannot fail that way.
    /// </para>
    /// <para>
    /// Every setter here must run on the UI thread — see <c>RunOnUi</c> in the other half
    /// of this class.
    /// </para>
    /// </remarks>
    public partial class SentinelDockable {

        // Semantic colours, fixed rather than themed: they have to stay legible on both
        // NINA's dark default and a light custom theme, and a DynamicResource that fails
        // to resolve would leave text the same colour as its background.
        private static readonly Brush OkBrush = Frozen(0xFF, 0x4C, 0xAF, 0x50);
        private static readonly Brush WarnBrush = Frozen(0xFF, 0xFF, 0xB3, 0x00);
        private static readonly Brush ErrorBrush = Frozen(0xFF, 0xEF, 0x53, 0x50);
        private static readonly Brush MutedBrush = Frozen(0xFF, 0x8A, 0x8A, 0x8A);

        private BitmapSource? frame;
        private double frameOpacity = 1.0;
        private Visibility frameVisibility = Visibility.Collapsed;
        private Visibility placeholderVisibility = Visibility.Visible;
        private string placeholderText = "Connecting to Sentinel…";
        private Visibility staleVisibility = Visibility.Collapsed;
        private string frameStatusText = string.Empty;
        private Brush frameStatusBrush = MutedBrush;
        private string healthStatusText = "UNKNOWN";
        private Brush healthBrush = MutedBrush;
        private IReadOnlyList<string> healthReasons = Array.Empty<string>();
        private Visibility healthReasonsVisibility = Visibility.Collapsed;
        private IReadOnlyList<SentinelStat> statistics = Array.Empty<SentinelStat>();
        private string linkNoticeText = string.Empty;
        private Visibility linkNoticeVisibility = Visibility.Collapsed;
        private Brush linkNoticeBrush = WarnBrush;
        private string commandsDisabledText = "Start/Stop unavailable: connecting to Sentinel…";
        private Visibility commandsDisabledVisibility = Visibility.Visible;
        private string commandMessageText = string.Empty;
        private Visibility commandMessageVisibility = Visibility.Collapsed;
        private Brush commandMessageBrush = MutedBrush;
        private bool canIssueCommands;
        private string endpointText = string.Empty;
        private Brush endpointBrush = MutedBrush;

        /// <summary>The latest frame from <c>/latest</c>, always frozen. Null when there is none.</summary>
        public BitmapSource? Frame {
            get => frame;
            private set => Set(ref frame, value);
        }

        /// <summary>Dims the frame when it is stale, so an old image never reads as current.</summary>
        public double FrameOpacity {
            get => frameOpacity;
            private set => Set(ref frameOpacity, value);
        }

        /// <summary>Whether the image element is shown.</summary>
        public Visibility FrameVisibility {
            get => frameVisibility;
            private set => Set(ref frameVisibility, value);
        }

        /// <summary>Whether the "no frame" message replaces the image.</summary>
        public Visibility PlaceholderVisibility {
            get => placeholderVisibility;
            private set => Set(ref placeholderVisibility, value);
        }

        /// <summary>Why there is no frame to show.</summary>
        public string PlaceholderText {
            get => placeholderText;
            private set => Set(ref placeholderText, value);
        }

        /// <summary>Whether the STALE badge is drawn over the frame.</summary>
        public Visibility StaleVisibility {
            get => staleVisibility;
            private set => Set(ref staleVisibility, value);
        }

        /// <summary>Frame age line, e.g. "Last frame 12s old — frame.jpg".</summary>
        public string FrameStatusText {
            get => frameStatusText;
            private set => Set(ref frameStatusText, value);
        }

        /// <summary>Amber once the frame is stale, muted otherwise.</summary>
        public Brush FrameStatusBrush {
            get => frameStatusBrush;
            private set => Set(ref frameStatusBrush, value);
        }

        /// <summary>Sentinel's health verb, upper-cased.</summary>
        public string HealthStatusText {
            get => healthStatusText;
            private set => Set(ref healthStatusText, value);
        }

        /// <summary>Colour matching <see cref="HealthStatusText"/>.</summary>
        public Brush HealthBrush {
            get => healthBrush;
            private set => Set(ref healthBrush, value);
        }

        /// <summary>
        /// Sentinel's own health reasons, rendered verbatim.
        /// </summary>
        /// <remarks>
        /// Already phrased for an operator ("no new frame for 900s — capture may be
        /// stalled"). Rewording them here would only lose detail.
        /// </remarks>
        public IReadOnlyList<string> HealthReasons {
            get => healthReasons;
            private set => Set(ref healthReasons, value);
        }

        /// <summary>Whether there are any reasons to list.</summary>
        public Visibility HealthReasonsVisibility {
            get => healthReasonsVisibility;
            private set => Set(ref healthReasonsVisibility, value);
        }

        /// <summary>
        /// Read-only statistics from <c>/status</c>, already formatted for a person.
        /// </summary>
        /// <remarks>
        /// Replaced wholesale on each poll rather than mutated, so the list can be built
        /// off the UI thread and handed over as an immutable snapshot.
        /// </remarks>
        public IReadOnlyList<SentinelStat> Statistics {
            get => statistics;
            private set => Set(ref statistics, value);
        }

        /// <summary>Why Sentinel cannot be reached, when it cannot.</summary>
        public string LinkNoticeText {
            get => linkNoticeText;
            private set => Set(ref linkNoticeText, value);
        }

        /// <summary>Whether the reachability notice is shown.</summary>
        public Visibility LinkNoticeVisibility {
            get => linkNoticeVisibility;
            private set => Set(ref linkNoticeVisibility, value);
        }

        /// <summary>Red when Sentinel is unreachable, amber for softer problems.</summary>
        public Brush LinkNoticeBrush {
            get => linkNoticeBrush;
            private set => Set(ref linkNoticeBrush, value);
        }

        /// <summary>
        /// Why Start/Stop are greyed out. Shown whenever <see cref="CanIssueCommands"/>
        /// is false, and never empty in that case.
        /// </summary>
        /// <remarks>
        /// Starts populated rather than blank: the window between the panel being built
        /// and the first control probe completing is real, and two dead buttons with no
        /// caption is indistinguishable from a broken panel.
        /// </remarks>
        public string CommandsDisabledText {
            get => commandsDisabledText;
            private set => Set(ref commandsDisabledText, value);
        }

        /// <summary>Visible exactly while the buttons are disabled.</summary>
        public Visibility CommandsDisabledVisibility {
            get => commandsDisabledVisibility;
            private set => Set(ref commandsDisabledVisibility, value);
        }

        /// <summary>Sentinel's verbatim answer to the last Start/Stop.</summary>
        public string CommandMessageText {
            get => commandMessageText;
            private set => Set(ref commandMessageText, value);
        }

        /// <summary>Whether a command result is being shown.</summary>
        public Visibility CommandMessageVisibility {
            get => commandMessageVisibility;
            private set => Set(ref commandMessageVisibility, value);
        }

        /// <summary>Red when the last command failed.</summary>
        public Brush CommandMessageBrush {
            get => commandMessageBrush;
            private set => Set(ref commandMessageBrush, value);
        }

        /// <summary>
        /// Drives the Start/Stop buttons' <c>IsEnabled</c> directly.
        /// </summary>
        /// <remarks>
        /// False while a command is in flight, and whenever control is not usable.
        /// Bound to <c>IsEnabled</c> rather than left to <c>ICommand.CanExecute</c> so
        /// the buttons cannot be re-armed by a stray <c>CommandManager</c> requery.
        /// </remarks>
        public bool CanIssueCommands {
            get => canIssueCommands;
            private set => Set(ref canIssueCommands, value);
        }

        /// <summary>The base URL in use, marked when it came from the options override. Never contains the token.</summary>
        public string EndpointText {
            get => endpointText;
            private set => Set(ref endpointText, value);
        }

        /// <summary>Amber while an override is in force, so a forgotten one is not invisible.</summary>
        public Brush EndpointBrush {
            get => endpointBrush;
            private set => Set(ref endpointBrush, value);
        }

        private static SolidColorBrush Frozen(byte a, byte r, byte g, byte b) {
            var brush = new SolidColorBrush(Color.FromArgb(a, r, g, b));
            brush.Freeze();
            return brush;
        }

        private void Set<T>(ref T field, T value, [CallerMemberName] string? propertyName = null) {
            if (EqualityComparer<T>.Default.Equals(field, value)) {
                return;
            }

            field = value;
            RaisePropertyChanged(propertyName);
        }
    }
}

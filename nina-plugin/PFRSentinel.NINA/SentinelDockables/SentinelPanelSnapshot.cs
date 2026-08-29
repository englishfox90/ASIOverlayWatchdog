#nullable enable
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Windows.Media.Imaging;

namespace PFRSentinel.NINA.SentinelDockables {

    /// <summary>
    /// Reachability of Sentinel's <em>unauthenticated</em> endpoints (/status, /latest).
    /// </summary>
    /// <remarks>
    /// Deliberately separate from <see cref="SentinelControlState"/>: /latest and /status
    /// need no token, so a Sentinel with the control API switched off is perfectly able to
    /// feed the panel a live frame. Collapsing the two axes would make the panel go blank
    /// for a configuration problem that does not affect it.
    /// </remarks>
    internal enum SentinelLinkState {

        /// <summary>No poll has completed yet.</summary>
        Connecting,

        /// <summary>The last poll reached Sentinel.</summary>
        Connected,

        /// <summary>Sentinel's config.json could not be found or read.</summary>
        Misconfigured,

        /// <summary>Nothing answered on the socket.</summary>
        Unreachable,

        /// <summary>Sentinel answered, but not with something we could use.</summary>
        Faulted,
    }

    /// <summary>Whether Start/Stop can be issued at all.</summary>
    internal enum SentinelControlState {

        /// <summary>Not probed yet.</summary>
        Unknown,

        /// <summary>Token accepted; commands may be issued.</summary>
        Available,

        /// <summary>No local config, or no token in it.</summary>
        NotConfigured,

        /// <summary>Control API switched off in Sentinel — HTTP 503 <c>control_disabled</c>.</summary>
        Disabled,

        /// <summary>Control enabled but no command handler registered — HTTP 503 <c>control_unavailable</c>.</summary>
        Unwired,

        /// <summary>The token was rejected.</summary>
        Unauthorized,

        /// <summary>Some other failure while probing control.</summary>
        Faulted,
    }

    /// <summary>
    /// One poll's worth of panel state, produced on the poll thread and applied
    /// wholesale on the UI thread.
    /// </summary>
    /// <remarks>
    /// Immutable by construction so it can cross threads without a lock.
    /// <see cref="Frame"/> is always a frozen <see cref="BitmapSource"/>.
    /// </remarks>
    internal sealed class SentinelPanelSnapshot {

        /// <summary>Reachability of the unauthenticated endpoints.</summary>
        public SentinelLinkState Link { get; init; }

        /// <summary>One-line description of <see cref="Link"/>, safe to display.</summary>
        public string LinkMessage { get; init; } = string.Empty;

        /// <summary>What the operator should do about <see cref="Link"/>. May be empty.</summary>
        public string LinkAdvice { get; init; } = string.Empty;

        /// <summary>Whether Start/Stop can be issued.</summary>
        public SentinelControlState Control { get; init; }

        /// <summary>One-line description of <see cref="Control"/>, safe to display.</summary>
        public string ControlMessage { get; init; } = string.Empty;

        /// <summary>What the operator should do about <see cref="Control"/>. May be empty.</summary>
        public string ControlAdvice { get; init; } = string.Empty;

        /// <summary>The latest frame, frozen, or null when there is none to show.</summary>
        public BitmapSource? Frame { get; init; }

        /// <summary>True when Sentinel answered 404 — it is running but has produced no image yet.</summary>
        public bool NoImageYet { get; init; }

        /// <summary>
        /// Age of <see cref="Frame"/> in seconds, or null when unknown.
        /// </summary>
        /// <remarks>
        /// Carried forward across 304s and extended by elapsed wall time: the 304
        /// path sends neither age nor stale, and reading their absence as "fresh"
        /// is exactly how an hours-old frame gets presented as current.
        /// </remarks>
        public int? AgeSeconds { get; init; }

        /// <summary>Whether the frame is past Sentinel's stale threshold.</summary>
        public bool Stale { get; init; }

        /// <summary>Bare filename of the frame, as Sentinel reports it.</summary>
        public string ImageName { get; init; } = string.Empty;

        /// <summary>Raw <c>health.status</c> string, or empty when Sentinel reported none.</summary>
        public string HealthStatus { get; init; } = string.Empty;

        /// <summary>Sentinel's own reason strings. Already operator-facing — render verbatim.</summary>
        public IReadOnlyList<string> HealthReasons { get; init; } = Array.Empty<string>();

        /// <summary>Fine-grained capture state, e.g. <c>capturing</c>, <c>outside_window</c>.</summary>
        public string CaptureState { get; init; } = string.Empty;

        /// <summary>Whether capture is producing frames.</summary>
        public bool CaptureRunning { get; init; }

        /// <summary>Capture mode: <c>camera</c>, <c>watch</c>, or <c>idle</c>.</summary>
        public string CaptureMode { get; init; } = string.Empty;

        /// <summary>Seconds the web server has been up, or null when Sentinel did not answer.</summary>
        public int? UptimeSeconds { get; init; }

        /// <summary>How many images the server has served, or null when Sentinel did not answer.</summary>
        public int? ImagesServed { get; init; }

        /// <summary>Configured seconds between captures. Null in watch mode.</summary>
        public double? IntervalSeconds { get; init; }

        /// <summary>Interval actually in effect, honouring variable-rate schedules.</summary>
        public double? EffectiveIntervalSeconds { get; init; }

        /// <summary>Seconds since the last successful capture, or null if there has been none.</summary>
        public int? LastCaptureAgeSeconds { get; init; }

        /// <summary>Estimated seconds to the next capture, or null when not predictable.</summary>
        public int? NextCaptureInSeconds { get; init; }

        /// <summary>Whether auto-recovery is under way.</summary>
        public bool RecoveryInProgress { get; init; }

        /// <summary>How many recovery attempts have been made.</summary>
        public int RecoveryAttempts { get; init; }

        /// <summary>Whether the camera is beyond automatic recovery.</summary>
        public bool RecoveryUnrecoverable { get; init; }

        /// <summary>Base URL in use. Never contains the token.</summary>
        public string Endpoint { get; init; } = string.Empty;

        /// <summary>
        /// Whether <see cref="Endpoint"/> came from the plugin's base URL override rather
        /// than from Sentinel's config.json.
        /// </summary>
        /// <remarks>
        /// Surfaced because a forgotten override is otherwise invisible: the panel points
        /// somewhere unexpected and every symptom looks like a Sentinel fault.
        /// </remarks>
        public bool EndpointIsOverride { get; init; }
    }

    /// <summary>Display formatting shared by the snapshot and the view model.</summary>
    internal static class SentinelPanelText {

        /// <summary>Renders a frame age as a compact human duration.</summary>
        public static string Age(int? seconds) =>
            seconds is int s ? Duration(s) : "age unknown";

        /// <summary>Renders a duration for the statistics block, or the unknown marker.</summary>
        public static string Span(int? seconds) =>
            seconds is int s ? Duration(s) : SentinelStat.Unknown;

        /// <summary>Renders a fractional-second interval, or the unknown marker.</summary>
        /// <remarks>
        /// Intervals arrive as doubles and are legitimately null in watch mode, where
        /// Sentinel does not choose when frames arrive.
        /// </remarks>
        public static string Span(double? seconds) =>
            seconds is double s ? Duration((int)Math.Round(Math.Max(0, s))) : SentinelStat.Unknown;

        /// <summary>Renders a count, or the unknown marker.</summary>
        public static string Count(int? value) =>
            value is int v ? v.ToString("N0", CultureInfo.CurrentCulture) : SentinelStat.Unknown;

        /// <summary>Compact human duration: "12s", "4m 20s", "3h 12m", "2d 4h".</summary>
        public static string Duration(int seconds) {
            int s = Math.Max(0, seconds);

            if (s < 60) {
                return $"{s}s";
            }

            if (s < 3600) {
                return $"{s / 60}m {s % 60}s";
            }

            if (s < 86400) {
                return $"{s / 3600}h {(s % 3600) / 60}m";
            }

            return $"{s / 86400}d {(s % 86400) / 3600}h";
        }

        /// <summary>Upper-cases Sentinel's health verb for the status line.</summary>
        public static string Health(string status) =>
            string.IsNullOrWhiteSpace(status) ? "UNKNOWN" : status.Trim().ToUpperInvariant();

        /// <summary>Turns <c>outside_window</c> into <c>outside window</c>.</summary>
        public static string CaptureState(string state) =>
            string.IsNullOrWhiteSpace(state) ? "unknown" : state.Replace('_', ' ');
    }
}

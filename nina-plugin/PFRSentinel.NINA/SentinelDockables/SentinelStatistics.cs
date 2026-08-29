#nullable enable
using System;
using System.Collections.Generic;

namespace PFRSentinel.NINA.SentinelDockables {

    /// <summary>
    /// Builds the panel's statistics rows from a poll snapshot.
    /// </summary>
    /// <remarks>
    /// Presentation only. Every figure comes straight from <c>/status</c> — nothing is
    /// derived, averaged or extrapolated, and a field Sentinel reported as null shows as
    /// <see cref="SentinelStat.Unknown"/> rather than a plausible-looking guess. Several
    /// are legitimately null: intervals in watch mode, capture ages before the first
    /// frame, and the next-capture estimate whenever it is not predictable.
    /// </remarks>
    internal static class SentinelStatistics {

        /// <summary>Rows shown when Sentinel has not been reached, so the block keeps its shape.</summary>
        private static readonly string[] Labels = {
            "Capture", "Interval", "Last frame", "Next frame", "Frame age", "Images served", "Uptime",
        };

        /// <summary>Formats one poll's statistics.</summary>
        public static IReadOnlyList<SentinelStat> Build(SentinelPanelSnapshot snapshot) {
            if (snapshot.Link != SentinelLinkState.Connected) {
                var unknown = new SentinelStat[Labels.Length];
                for (int i = 0; i < Labels.Length; i++) {
                    unknown[i] = new SentinelStat(Labels[i], SentinelStat.Unknown);
                }

                return unknown;
            }

            var rows = new List<SentinelStat>(8) {
                new("Capture", Capture(snapshot)),
                new("Interval", Interval(snapshot)),
                new("Last frame", Ago(snapshot.LastCaptureAgeSeconds)),
                new("Next frame", Next(snapshot.NextCaptureInSeconds)),
                new("Frame age", FrameAge(snapshot)),
                new("Images served", SentinelPanelText.Count(snapshot.ImagesServed)),
                new("Uptime", SentinelPanelText.Span(snapshot.UptimeSeconds)),
            };

            string? recovery = Recovery(snapshot);
            if (recovery is not null) {
                // Only when there is something to report: a "Recovery: none" row every
                // night is noise, and the row appearing is itself the signal.
                rows.Add(new SentinelStat("Recovery", recovery));
            }

            return rows;
        }

        private static string Capture(SentinelPanelSnapshot snapshot) {
            string state = SentinelPanelText.CaptureState(snapshot.CaptureState);
            if (state == "unknown") {
                return SentinelStat.Unknown;
            }

            return snapshot.CaptureMode.Length > 0 ? $"{state} ({snapshot.CaptureMode})" : state;
        }

        private static string Interval(SentinelPanelSnapshot snapshot) {
            double? configured = snapshot.IntervalSeconds;
            double? effective = snapshot.EffectiveIntervalSeconds;

            if (configured is null && effective is null) {
                return SentinelStat.Unknown;
            }

            if (configured is null) {
                return SentinelPanelText.Span(effective);
            }

            // A variable-rate schedule makes the two differ, and the effective one is
            // what the next frame will actually wait for.
            if (effective is not null && Math.Abs(effective.Value - configured.Value) > 0.5) {
                return $"{SentinelPanelText.Span(effective)} (set {SentinelPanelText.Span(configured)})";
            }

            return SentinelPanelText.Span(configured);
        }

        private static string Ago(int? seconds) =>
            seconds is int s ? $"{SentinelPanelText.Duration(s)} ago" : SentinelStat.Unknown;

        private static string Next(int? seconds) =>
            seconds is int s ? $"in {SentinelPanelText.Duration(s)}" : SentinelStat.Unknown;

        private static string FrameAge(SentinelPanelSnapshot snapshot) {
            if (snapshot.AgeSeconds is not int age) {
                return SentinelStat.Unknown;
            }

            string text = SentinelPanelText.Duration(age);
            return snapshot.Stale ? $"{text} (stale)" : text;
        }

        private static string? Recovery(SentinelPanelSnapshot snapshot) {
            if (snapshot.RecoveryUnrecoverable) {
                return "unrecoverable — restart Sentinel";
            }

            if (snapshot.RecoveryInProgress) {
                return snapshot.RecoveryAttempts > 0
                    ? $"in progress (attempt {snapshot.RecoveryAttempts})"
                    : "in progress";
            }

            if (snapshot.RecoveryAttempts > 0) {
                return $"{snapshot.RecoveryAttempts} attempt(s) so far";
            }

            return null;
        }
    }
}

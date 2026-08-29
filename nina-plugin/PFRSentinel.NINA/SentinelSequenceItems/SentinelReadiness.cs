#nullable enable
using PFRSentinel.Nina.Client;
using System;
using System.Collections.Generic;

namespace PFRSentinel.NINA.SentinelSequenceItems {

    /// <summary>Result of one Start or Stop, reduced to what a sequence step needs.</summary>
    internal sealed class SentinelCommandOutcome {

        /// <summary>
        /// Whether Sentinel accepted the command.
        /// </summary>
        /// <remarks>
        /// Idempotency is decided by the server: every 2xx is a success, and that
        /// deliberately includes <c>already_running</c> and <c>already_stopped</c>. A
        /// sequence that re-runs Start, or fires Stop twice while aborting, must not
        /// fail on the second call.
        /// </remarks>
        public bool Succeeded { get; init; }

        /// <summary>
        /// The one line to log, and to fail the sequence step with.
        /// </summary>
        /// <remarks>
        /// <para>
        /// When Sentinel answered with a control result - which includes the 500 that
        /// carries a real capture failure - this is its own wording, verbatim ("No ZWO
        /// cameras detected. Check USB connections."), lifted by
        /// <c>api_control._message</c> straight out of capture's last error.
        /// Substituting a generic phrase throws away the only thing that tells the
        /// operator what to go and fix.
        /// </para>
        /// <para>
        /// When the request never produced a control result at all - unreachable, 401,
        /// 503 - this is instead the curated line from
        /// <see cref="SentinelReadiness.Describe"/>, so a failure and the validation
        /// issue for the same cause read identically.
        /// </para>
        /// </remarks>
        public string Message { get; init; } = string.Empty;
    }

    /// <summary>
    /// Whether Sentinel can be commanded right now, as last observed.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Immutable and NINA-free so the whole mapping from a client failure to the
    /// sentence a sequencer shows can be exercised from a console harness.
    /// </para>
    /// <para>
    /// <see cref="Unknown"/> carries no issues on purpose. It means "not probed yet",
    /// and a validation pass that has not yet heard from Sentinel must not accuse it
    /// of being down — NINA re-validates every few seconds, so the real answer lands
    /// almost immediately.
    /// </para>
    /// </remarks>
    internal sealed class SentinelReadiness {

        private static readonly IReadOnlyList<string> NoIssues = Array.Empty<string>();

        /// <summary>
        /// The one wording for "control is on, but no handler is registered".
        /// </summary>
        /// <remarks>
        /// Shared because this condition arrives by two routes that must not disagree:
        /// the <c>control_ready</c> flag on a pre-flight probe, and a
        /// <c>control_unavailable</c> 503 from a command that got there first.
        /// </remarks>
        public const string ControlUnwiredIssue =
            "PFR Sentinel is running but capture control is not wired up. Restart Sentinel.";

        /// <summary>Nothing has been probed yet.</summary>
        public static readonly SentinelReadiness Unknown = new();

        private SentinelReadiness() {
        }

        /// <summary>Whether a probe has completed at all.</summary>
        public bool IsKnown { get; private init; }

        /// <summary>When the probe that produced this snapshot finished.</summary>
        public DateTime ProbedAtUtc { get; private init; }

        /// <summary>Validation issues, empty when Sentinel is ready.</summary>
        public IReadOnlyList<string> Issues { get; private init; } = NoIssues;

        /// <summary>Creates a snapshot for a Sentinel that answered an authenticated probe.</summary>
        public static SentinelReadiness Ready(DateTime nowUtc) =>
            new() { IsKnown = true, ProbedAtUtc = nowUtc };

        /// <summary>
        /// Creates a snapshot for a Sentinel that answered, but reported that no
        /// capture command handler is registered.
        /// </summary>
        public static SentinelReadiness Unwired(DateTime nowUtc) =>
            new() { IsKnown = true, ProbedAtUtc = nowUtc, Issues = new[] { ControlUnwiredIssue } };

        /// <summary>Creates a snapshot from a client failure.</summary>
        public static SentinelReadiness FromFailure(SentinelException failure, DateTime nowUtc) =>
            new() { IsKnown = true, ProbedAtUtc = nowUtc, Issues = new[] { Describe(failure) } };

        /// <summary>Creates a snapshot from a failure the client does not model.</summary>
        public static SentinelReadiness FromUnexpected(Exception failure, DateTime nowUtc) =>
            new() {
                IsKnown = true,
                ProbedAtUtc = nowUtc,
                Issues = new[] {
                    $"PFR Sentinel could not be checked ({failure.GetType().Name}: {failure.Message}). See NINA's log for detail."
                }
            };

        /// <summary>
        /// One actionable line per failure kind, for a validation issue or a failed
        /// sequence step.
        /// </summary>
        /// <remarks>
        /// <para>
        /// Written out per kind rather than deferred to
        /// <see cref="SentinelException.OperatorAdvice"/> alone, because a validation
        /// list needs the cause and the fix in the same sentence - "Sentinel is not
        /// reachable" and "enable it on the Output tab" are useless apart. Pasting the
        /// two together mechanically does not work either: for several kinds the advice
        /// restates the message, and the operator gets the same sentence twice.
        /// </para>
        /// <para>
        /// The 503/401 cases are the ones that earn the hand-writing: they look
        /// identical to an operator and need opposite actions, and only
        /// <see cref="SentinelException.Kind"/> - derived from the server's
        /// machine-readable <c>code</c>, never its prose - separates them.
        /// </para>
        /// </remarks>
        public static string Describe(SentinelException failure) => failure.Kind switch {
            SentinelErrorKind.ControlDisabled =>
                "PFR Sentinel's capture control API is switched off. Enable it on Sentinel's Output tab.",

            SentinelErrorKind.ControlUnavailable =>
                ControlUnwiredIssue,

            SentinelErrorKind.Unauthorized =>
                "PFR Sentinel rejected the control token. Regenerate it on Sentinel's Output tab.",

            SentinelErrorKind.Unreachable =>
                failure.Message + " Check Sentinel is running with its web server enabled, and that the host and port match.",

            SentinelErrorKind.HostNotAllowed =>
                "PFR Sentinel refused the request's Host header. Capture control is accepted from the same machine only, unless extra hosts are allow-listed in Sentinel's config.",

            SentinelErrorKind.ConfigNotFound =>
                failure.Message,

            SentinelErrorKind.ClientTimeout =>
                "PFR Sentinel did not answer in time. Check it is running and not blocked by a firewall.",

            _ =>
                "PFR Sentinel: " + failure.Message + " " + failure.OperatorAdvice,
        };
    }
}

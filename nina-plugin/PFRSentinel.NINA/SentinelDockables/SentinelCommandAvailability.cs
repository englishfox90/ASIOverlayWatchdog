#nullable enable

namespace PFRSentinel.NINA.SentinelDockables {

    /// <summary>
    /// Decides whether Start/Stop can be issued, and — always — why not.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Split out as pure logic so the rule can be asserted directly in a test harness,
    /// without standing up a <c>DockableVM</c>. The rule that matters most is the one
    /// that is easiest to get wrong by accident: <b>health plays no part in it</b>. A
    /// camera fault is exactly the moment an operator wants to plug the camera back in
    /// and press Start, so an <c>error</c> health verdict must never grey the buttons.
    /// Only the availability of the control API does that.
    /// </para>
    /// <para>
    /// <see cref="DescribeBlock"/> returns a non-empty string for every state in which
    /// <see cref="CanIssue"/> is false. Disabled buttons with no explanation beside them
    /// are indistinguishable from a broken panel.
    /// </para>
    /// </remarks>
    internal static class SentinelCommandAvailability {

        /// <summary>Whether Start/Stop may be issued. Health is deliberately not consulted.</summary>
        public static bool CanIssue(SentinelControlState control) =>
            control == SentinelControlState.Available;

        /// <summary>
        /// Why the buttons are dead, or an empty string when they are live.
        /// </summary>
        /// <param name="control">Availability of the control API.</param>
        /// <param name="link">Reachability of Sentinel, used to explain an unresolved probe.</param>
        /// <param name="commandInFlight">Whether a command is currently on the wire.</param>
        public static string DescribeBlock(
            SentinelControlState control,
            SentinelLinkState link,
            bool commandInFlight) {

            if (commandInFlight) {
                return "Waiting for Sentinel to confirm the last command…";
            }

            if (CanIssue(control)) {
                return string.Empty;
            }

            return control switch {
                SentinelControlState.Disabled =>
                    "Start/Stop unavailable: the capture control API is switched off in Sentinel.",
                SentinelControlState.Unwired =>
                    "Start/Stop unavailable: Sentinel is running but capture control is not wired up.",
                SentinelControlState.Unauthorized =>
                    "Start/Stop unavailable: Sentinel rejected the control token.",
                SentinelControlState.NotConfigured =>
                    "Start/Stop unavailable: no capture control token is configured.",
                SentinelControlState.Faulted =>
                    "Start/Stop unavailable: capture control could not be reached.",

                // Unknown used to disable the buttons while showing nothing at all —
                // a panel polling happily with two dead buttons and no reason given.
                _ when link == SentinelLinkState.Connected =>
                    "Start/Stop unavailable: still checking whether capture control is available…",
                _ =>
                    "Start/Stop unavailable: Sentinel has not been reached yet.",
            };
        }
    }
}

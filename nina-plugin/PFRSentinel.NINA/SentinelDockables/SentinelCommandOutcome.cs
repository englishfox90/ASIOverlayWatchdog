#nullable enable

namespace PFRSentinel.NINA.SentinelDockables {

    /// <summary>Result of one Start or Stop, already reduced to what the panel shows.</summary>
    internal sealed class SentinelCommandOutcome {

        /// <summary>Whether Sentinel accepted the command. Idempotent no-ops count as success.</summary>
        public bool Succeeded { get; init; }

        /// <summary>
        /// Sentinel's own wording, verbatim.
        /// </summary>
        /// <remarks>
        /// On a failure this is the real cause ("No ZWO cameras detected. Check USB
        /// connections."). Substituting a generic phrase here throws away the only
        /// thing that tells the operator what to go and fix.
        /// </remarks>
        public string Message { get; init; } = string.Empty;

        /// <summary>Follow-up action, when the client offered one. May be empty.</summary>
        public string Advice { get; init; } = string.Empty;
    }
}

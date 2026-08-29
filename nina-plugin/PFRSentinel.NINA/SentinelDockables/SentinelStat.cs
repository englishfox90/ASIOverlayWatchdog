#nullable enable

namespace PFRSentinel.NINA.SentinelDockables {

    /// <summary>One row of the panel's statistics block.</summary>
    /// <remarks>
    /// Public, unlike the rest of the panel's internals: WPF's reflection-based binding
    /// cannot read properties off an internal type, and the failure is a silent blank
    /// row rather than an error.
    /// <para>
    /// Every value is already formatted for a person — <c>"3h 12m"</c>, never
    /// <c>11520</c>, and <see cref="Unknown"/> where Sentinel reported null. Nothing
    /// here is derived: if the API did not supply a number, the row says so.
    /// </para>
    /// </remarks>
    public sealed class SentinelStat {

        /// <summary>Shown where Sentinel reported no value. Several fields are legitimately null.</summary>
        public const string Unknown = "—";

        /// <summary>Creates a row.</summary>
        public SentinelStat(string label, string value) {
            Label = label;
            Value = value;
        }

        /// <summary>Left column, e.g. "Uptime".</summary>
        public string Label { get; }

        /// <summary>Right column, already human-formatted.</summary>
        public string Value { get; }
    }
}

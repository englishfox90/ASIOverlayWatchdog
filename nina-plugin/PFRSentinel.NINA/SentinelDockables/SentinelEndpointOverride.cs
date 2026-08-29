#nullable enable
using System;

namespace PFRSentinel.NINA.SentinelDockables {

    /// <summary>
    /// Validates the operator-typed base URL override before it reaches the client.
    /// </summary>
    /// <remarks>
    /// <para>
    /// <c>SentinelConfig.Load</c> applies a base URL override with nothing but a
    /// <c>TrimEnd('/')</c> — it does not validate. Garbage therefore survives all the way
    /// to <c>new Uri(BaseUrl + ImagePath)</c> and surfaces as a <c>UriFormatException</c>
    /// from deep inside the poll, which the panel can only report as a generic fault.
    /// Checking here turns "something went wrong" into "this is the bad value, and this
    /// is where you typed it".
    /// </para>
    /// <para>
    /// The scheme check is not redundant. <c>Uri.TryCreate("192.168.1.10:8080", Absolute)</c>
    /// <em>succeeds</em>, parsing <c>192.168.1.10</c> as the scheme — so a host:port with
    /// no scheme sails past a bare TryCreate and fails much later.
    /// </para>
    /// </remarks>
    internal readonly struct SentinelEndpointOverride {

        private SentinelEndpointOverride(bool isValid, string baseUrl, string problem) {
            IsValid = isValid;
            BaseUrl = baseUrl;
            Problem = problem;
        }

        /// <summary>Whether <see cref="BaseUrl"/> may be handed to the client.</summary>
        public bool IsValid { get; }

        /// <summary>The normalised base URL: scheme, authority and path, no trailing slash.</summary>
        public string BaseUrl { get; }

        /// <summary>Why the value was rejected, naming it. Empty when valid.</summary>
        public string Problem { get; }

        /// <summary>Validates and normalises a value typed into the plugin options.</summary>
        /// <param name="raw">The raw setting. Null or blank is not an override.</param>
        public static SentinelEndpointOverride Parse(string? raw) {
            string text = (raw ?? string.Empty).Trim();

            if (text.Length == 0) {
                return new SentinelEndpointOverride(false, string.Empty, string.Empty);
            }

            // Checked before TryCreate because "192.168.1.10:8080" fails to parse at all
            // (a scheme may not start with a digit), and "not a complete URL" would send
            // the operator hunting for a typo when they simply omitted http://.
            if (!text.Contains("://", StringComparison.Ordinal)) {
                return Invalid(text, "it must start with http:// or https://");
            }

            if (!Uri.TryCreate(text, UriKind.Absolute, out Uri? uri)) {
                return Invalid(text, "it is not a complete URL");
            }

            if (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps) {
                return Invalid(text, "it must start with http:// or https://");
            }

            if (uri.Host.Length == 0) {
                return Invalid(text, "it does not name a host");
            }

            // GetLeftPart(Path) drops any query or fragment, which are meaningless on a
            // base URL and would otherwise be spliced in front of "/latest".
            string normalised = uri.GetLeftPart(UriPartial.Path).TrimEnd('/');

            return normalised.Length == 0
                ? Invalid(text, "it does not name a host")
                : new SentinelEndpointOverride(true, normalised, string.Empty);
        }

        private static SentinelEndpointOverride Invalid(string text, string because) =>
            new(false, string.Empty,
                $"The Sentinel base URL override “{text}” cannot be used — {because}.");
    }
}

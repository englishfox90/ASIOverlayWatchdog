#nullable enable
using PFRSentinel.Nina.Client;
using PFRSentinel.NINA.SentinelDockables;
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace PFRSentinel.NINA.SentinelSequenceItems {

    /// <summary>
    /// The one <see cref="SentinelClient"/> shared by every Sentinel sequence item,
    /// plus the cached reachability answer their <c>Validate()</c> reads.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Deliberately free of any NINA type, so the whole network-facing half of both
    /// instructions can be driven against a live Sentinel from a console harness. The
    /// plugin-options override arrives as a plain string for the same reason.
    /// </para>
    /// <para>
    /// <b>Why the readiness answer is cached and shared.</b> NINA re-validates the
    /// entire sequence from a background timer
    /// (<c>Sequence2VM.RunBackgroundValidationTimer</c> calls
    /// <c>MainContainer.Validate()</c>, which cascades to every item). A
    /// <c>Validate()</c> that made its own HTTP call would therefore fire once per
    /// Sentinel instruction per tick, forever. One cached snapshot, refreshed at most
    /// every <see cref="ReadinessLifetime"/> and never by more than one probe at a
    /// time, turns that into a single cheap request.
    /// </para>
    /// <para>
    /// Process-lifetime by design: NINA has no plugin-unload hook to dispose it in, and
    /// the client holds one idle <see cref="System.Net.Http.HttpClient"/>.
    /// </para>
    /// </remarks>
    internal sealed class SentinelSequenceLink {

        /// <summary>How long a probe result is reused before another is started.</summary>
        public static readonly TimeSpan ReadinessLifetime = TimeSpan.FromSeconds(10);

        // A validation probe must never outlive a validation tick by much. Only
        // non-waiting requests use this budget, so it cannot truncate a wait:true
        // command, whose budget is its own timeout plus the client margin.
        private static readonly TimeSpan ProbeTimeout = TimeSpan.FromSeconds(8);

        private static readonly Lazy<SentinelSequenceLink> LazyInstance =
            new(() => new SentinelSequenceLink(), LazyThreadSafetyMode.ExecutionAndPublication);

        private readonly SentinelConfigOverrides baseOverrides;
        private readonly object gate = new();
        private readonly List<SentinelClient> retired = new();

        private Endpoint endpoint;
        private string appliedOverride = string.Empty;
        private int inFlight;

        private volatile SentinelReadiness readiness = SentinelReadiness.Unknown;
        private int probing;

        /// <summary>Creates a link, optionally against an explicit endpoint (harness use).</summary>
        public SentinelSequenceLink(SentinelConfigOverrides? overrides = null) {
            baseOverrides = overrides ?? new SentinelConfigOverrides();
            endpoint = Endpoint.Create(baseOverrides);
        }

        /// <summary>The shared link used by the sequence items.</summary>
        public static SentinelSequenceLink Instance => LazyInstance.Value;

        /// <summary>The base URL override currently in force, or empty for none.</summary>
        public string AppliedOverride {
            get { lock (gate) { return appliedOverride; } }
        }

        /// <summary>
        /// Points the link at the base URL typed into the plugin options, if it changed.
        /// </summary>
        /// <param name="raw">
        /// The raw setting value. Null, blank, or unparseable means "no override" and
        /// falls back to Sentinel's own config.json.
        /// </param>
        /// <remarks>
        /// <para>
        /// The same accessor and the same validation the dockable panel uses, so the two
        /// halves of the plugin can never end up talking to different Sentinels.
        /// </para>
        /// <para>
        /// A rejected value falls back rather than raising its own validation issue. The
        /// options page is where a typo gets reported; a sequence item that shouted
        /// about it too would put the same complaint on every instruction in the
        /// sequence.
        /// </para>
        /// </remarks>
        public void ApplyEndpointOverride(string? raw) {
            SentinelEndpointOverride parsed = SentinelEndpointOverride.Parse(raw);
            string wanted = parsed.IsValid ? parsed.BaseUrl : string.Empty;

            lock (gate) {
                if (string.Equals(wanted, appliedOverride, StringComparison.Ordinal)) {
                    return;
                }

                retired.Add(endpoint.Client);
                appliedOverride = wanted;
                endpoint = Endpoint.Create(baseOverrides, wanted.Length == 0 ? null : wanted);
            }

            // A cached answer describes the old address and would be actively
            // misleading about the new one.
            readiness = SentinelReadiness.Unknown;
        }

        /// <summary>
        /// The last known readiness, starting a refresh in the background when the
        /// cached answer is missing or stale.
        /// </summary>
        /// <remarks>
        /// Returns immediately, always. This is what keeps <c>Validate()</c> off the
        /// wire: it reads a field, and the network work happens on a pool thread whose
        /// result the next validation tick picks up.
        /// </remarks>
        public SentinelReadiness GetReadiness() => GetReadiness(DateTime.UtcNow);

        /// <summary>Testable overload of <see cref="GetReadiness()"/>.</summary>
        public SentinelReadiness GetReadiness(DateTime nowUtc) {
            SentinelReadiness current = readiness;
            if (!current.IsKnown || nowUtc - current.ProbedAtUtc >= ReadinessLifetime) {
                BeginProbe();
            }

            return current;
        }

        /// <summary>Starts a probe unless one is already running.</summary>
        public void BeginProbe() {
            if (Interlocked.CompareExchange(ref probing, 1, 0) != 0) {
                return;
            }

            _ = Task.Run(async () => {
                try {
                    readiness = await ProbeAsync(CancellationToken.None).ConfigureAwait(false);
                } finally {
                    Volatile.Write(ref probing, 0);
                }
            });
        }

        /// <summary>
        /// Asks Sentinel whether it is reachable, authenticated, and able to accept a
        /// capture command.
        /// </summary>
        /// <remarks>
        /// <para>
        /// The authenticated control GET mutates nothing, so one request settles all
        /// four things a sequence needs to know before the night starts: that Sentinel
        /// answers, that the token is accepted, that the control API is enabled, and -
        /// from the <c>control_ready</c> flag on the same body - that a capture command
        /// handler is actually registered.
        /// </para>
        /// <para>
        /// <b>A missing <c>control_ready</c> is not a false one.</b> A Sentinel built
        /// before the field existed simply omits it, and treating silence as "not wired"
        /// would fail validation across a whole sequence against an observatory that is
        /// working perfectly. Unknown means assume ready; the
        /// <c>control_unavailable</c> 503 from <see cref="SendAsync"/> remains the
        /// backstop that catches such a Sentinel the first time a command runs.
        /// </para>
        /// <para>
        /// The config is re-read first because the fix for most of these issues (enable
        /// control, regenerate the token) rewrites Sentinel's config.json. Without the
        /// reload, a plugin that started while control was off would keep failing from
        /// its cached copy and never notice it had been turned on.
        /// </para>
        /// <para>Never throws: every failure becomes a readiness snapshot.</para>
        /// </remarks>
        public async Task<SentinelReadiness> ProbeAsync(CancellationToken cancellationToken) {
            Endpoint current = Current();
            Interlocked.Increment(ref inFlight);

            try {
                current.Client.ReloadConfiguration();

                SentinelCaptureState state = await current.Client
                    .GetCaptureStateAsync(cancellationToken).ConfigureAwait(false);

                // Null means the server predates the field — assume ready rather
                // than failing validation against an older Sentinel.
                return state.ControlReady == false
                    ? SentinelReadiness.Unwired(DateTime.UtcNow)
                    : SentinelReadiness.Ready(DateTime.UtcNow);
            } catch (SentinelException ex) {
                return SentinelReadiness.FromFailure(ex, DateTime.UtcNow);
            } catch (OperationCanceledException) {
                return SentinelReadiness.Unknown;
            } catch (Exception ex) {
                return SentinelReadiness.FromUnexpected(ex, DateTime.UtcNow);
            } finally {
                Release();
            }
        }

        /// <summary>
        /// Issues Start or Stop and waits for capture to reach the target state.
        /// </summary>
        /// <param name="start">True for Start, false for Stop.</param>
        /// <param name="timeoutSeconds">Server-side wait budget, 1-300 seconds.</param>
        /// <param name="cancellationToken">The sequence token.</param>
        /// <returns>The outcome, carrying Sentinel's verbatim message.</returns>
        /// <remarks>
        /// <para>
        /// <c>wait: true</c> is what makes the instruction deterministic - the sequence
        /// must not advance while capture is still spinning up.
        /// </para>
        /// <para>
        /// Only modelled Sentinel failures become an outcome. Anything else propagates
        /// with its stack intact, because an unexpected exception is a plugin bug and
        /// flattening it to a one-line message would hide the only evidence of it.
        /// </para>
        /// </remarks>
        public async Task<SentinelCommandOutcome> SendAsync(bool start, int timeoutSeconds, CancellationToken cancellationToken) {
            var options = new SentinelCommandOptions {
                Wait = true,
                TimeoutSeconds = Math.Clamp(
                    timeoutSeconds,
                    SentinelCommandOptions.MinTimeoutSeconds,
                    SentinelCommandOptions.MaxTimeoutSeconds),

                // See StartSentinelCapture.Execute for why abandoning is the right
                // answer here, and why nothing is issued to compensate.
                CancellationBehaviour = SentinelCancellation.AbandonRequest,
            };

            Endpoint current = Current();
            Interlocked.Increment(ref inFlight);

            try {
                current.Client.ReloadConfiguration();

                SentinelControlResult result = start
                    ? await current.Client.StartAsync(options, cancellationToken).ConfigureAwait(false)
                    : await current.Client.StopAsync(options, cancellationToken).ConfigureAwait(false);

                // The command proved reachability and the token more thoroughly than a
                // probe could, so validation should not re-ask a moment later.
                readiness = SentinelReadiness.Ready(DateTime.UtcNow);

                return new SentinelCommandOutcome {
                    Succeeded = result.IsSuccess,
                    Message = result.Message.Length > 0 ? result.Message : result.ToString(),
                };
            } catch (SentinelException ex) {
                // The backstop for an older Sentinel that cannot report control_ready:
                // its control_unavailable 503 only exists on a real command, and this is
                // what carries it into validation from then on.
                readiness = SentinelReadiness.FromFailure(ex, DateTime.UtcNow);

                return new SentinelCommandOutcome {
                    Succeeded = false,
                    Message = SentinelReadiness.Describe(ex),
                };
            } finally {
                Release();
            }
        }

        private Endpoint Current() {
            lock (gate) {
                return endpoint;
            }
        }

        /// <summary>
        /// Marks one operation finished, disposing any retired clients once nothing at
        /// all is in flight.
        /// </summary>
        /// <remarks>
        /// Re-pointing the base URL cannot dispose the outgoing client on the spot: a
        /// <c>wait: true</c> command may legitimately still be holding it open for
        /// minutes, and disposing underneath it turns an in-progress sequence step into
        /// an <see cref="ObjectDisposedException"/>. Counting instead means the swap is
        /// free and the sockets still close.
        /// </remarks>
        private void Release() {
            if (Interlocked.Decrement(ref inFlight) != 0) {
                return;
            }

            SentinelClient[] doomed;
            lock (gate) {
                if (retired.Count == 0) {
                    return;
                }

                doomed = retired.ToArray();
                retired.Clear();
            }

            foreach (SentinelClient client in doomed) {
                try {
                    client.Dispose();
                } catch (Exception) {
                    // A client we are already finished with cannot fail usefully.
                }
            }
        }

        /// <summary>One client bound to one endpoint.</summary>
        private sealed class Endpoint {

            private Endpoint(SentinelClient client) {
                Client = client;
            }

            public SentinelClient Client { get; }

            public static Endpoint Create(SentinelConfigOverrides baseOverrides, string? baseUrl = null) {
                var overrides = new SentinelConfigOverrides {
                    BaseUrl = baseUrl ?? baseOverrides.BaseUrl,
                    Token = baseOverrides.Token,
                    ConfigPath = baseOverrides.ConfigPath,
                    ControlPath = baseOverrides.ControlPath,
                    StatusPath = baseOverrides.StatusPath,
                    ImagePath = baseOverrides.ImagePath,
                };

                var client = new SentinelClient(new SentinelConfigProvider(overrides)) {
                    ReadTimeout = ProbeTimeout,
                };

                return new Endpoint(client);
            }
        }
    }
}

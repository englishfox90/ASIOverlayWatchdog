#nullable enable
using PFRSentinel.Nina.Client;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Media.Imaging;

namespace PFRSentinel.NINA.SentinelDockables {

    /// <summary>
    /// Owns the <see cref="SentinelClient"/> and the poll loop behind the dockable panel.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Deliberately free of any NINA type so the whole network-facing half of the panel
    /// can be exercised against a live Sentinel from a console harness. The view model
    /// adds only marshalling and formatting on top.
    /// </para>
    /// <para>
    /// The loop never throws: every failure becomes a <see cref="SentinelPanelSnapshot"/>
    /// describing it. An exception escaping into the timer would kill the loop for the
    /// rest of the session and the panel would silently freeze on its last frame.
    /// </para>
    /// </remarks>
    internal sealed class SentinelPoller : IDisposable {

        /// <summary>Poll period while the panel is visible.</summary>
        public static readonly TimeSpan DefaultInterval = TimeSpan.FromSeconds(4);

        // While hidden the loop issues no requests at all; it only wakes often enough
        // to notice IsVisible flipping back, and Wake() short-circuits even that.
        private static readonly TimeSpan HiddenIdle = TimeSpan.FromSeconds(2);

        // The authenticated probe costs a request and only answers a question that
        // changes when the operator edits Sentinel's settings, so it runs far less
        // often than the frame poll.
        private static readonly TimeSpan ControlProbeInterval = TimeSpan.FromSeconds(60);

        private readonly SentinelConfigOverrides _baseOverrides;
        private readonly Func<string?> _overrideSource;
        private readonly List<SentinelClient> _retiredClients = new();
        private readonly object _clientGate = new();
        private readonly CancellationTokenSource _cts = new();
        private readonly SemaphoreSlim _wake = new(0, 1);

        // Swapped, not mutated, when the operator edits the base URL override:
        // SentinelConfigProvider takes its overrides at construction and a client holds
        // its provider for life, so a new endpoint means a new client.
        private volatile SentinelClient _client;

        private string _appliedOverride = string.Empty;
        private string _overrideProblem = string.Empty;
        private string _activeOverrideUrl = string.Empty;

        private Task? _loop;
        private volatile bool _visible;
        private volatile bool _disposed;

        private string? _etag;
        private BitmapSource? _frame;
        private string _imageName = string.Empty;
        private bool _noImageYet;
        private string? _imageError;

        // Carried across 304s, which send neither age nor stale.
        private int? _lastKnownAge;
        private DateTime _lastKnownAgeAtUtc = DateTime.UtcNow;
        private bool _lastKnownStale;
        private int? _staleThresholdSeconds;

        private DateTime _lastControlProbeUtc = DateTime.MinValue;
        private SentinelControlState _control = SentinelControlState.Unknown;
        private string _controlMessage = string.Empty;
        private string _controlAdvice = string.Empty;

        /// <summary>Creates a poller, optionally overriding Sentinel's discovered endpoint.</summary>
        /// <param name="overrides">Fixed overrides, e.g. an explicit config.json path for tests.</param>
        /// <param name="baseUrlOverrideSource">
        /// Reads the operator's base URL override, re-read at the top of every poll.
        /// </param>
        /// <remarks>
        /// The override arrives as a callback rather than a value so an edit on the
        /// options page takes effect on the next poll, with no restart and no eventing
        /// between two MEF exports that hold no reference to each other.
        /// </remarks>
        public SentinelPoller(
            SentinelConfigOverrides? overrides = null,
            Func<string?>? baseUrlOverrideSource = null) {

            _baseOverrides = overrides ?? new SentinelConfigOverrides();
            _overrideSource = baseUrlOverrideSource ?? (() => null);
            _client = new SentinelClient(new SentinelConfigProvider(_baseOverrides));
        }

        /// <summary>Raised on the poll thread after every completed poll.</summary>
        public event Action<SentinelPanelSnapshot>? SnapshotReady;

        /// <summary>Poll period while visible.</summary>
        public TimeSpan Interval { get; set; } = DefaultInterval;

        /// <summary>
        /// Whether the panel is on screen. False suspends all network traffic.
        /// </summary>
        /// <remarks>
        /// A NINA session runs all night with most dockables hidden; a panel that keeps
        /// polling behind a tab nobody is looking at is pure waste.
        /// </remarks>
        public bool Visible {
            get => _visible;
            set {
                if (_visible == value) {
                    return;
                }

                _visible = value;
                if (value) {
                    Wake();
                }
            }
        }

        /// <summary>Starts the loop. Idempotent.</summary>
        public void Start() {
            if (_disposed || _loop is not null) {
                return;
            }

            _loop = Task.Run(() => RunAsync(_cts.Token));
        }

        /// <summary>Forces the next poll to happen now instead of at the end of the period.</summary>
        public void RequestPollNow() => Wake();

        /// <summary>
        /// Re-reads Sentinel's config.json and re-probes control on the next poll.
        /// </summary>
        /// <remarks>
        /// Sentinel can regenerate its control token while NINA is running, which turns
        /// every subsequent command into a 401 with no obvious cause. This is the manual
        /// way out of that.
        /// </remarks>
        public void Reconnect() {
            try {
                _client.ReloadConfiguration();
            } catch (Exception) {
                // SentinelConfig.Load reports problems through Status rather than
                // throwing, so this is belt and braces; the next poll surfaces the state.
            }

            // Force the override to be re-read and re-validated too, not just the file.
            _appliedOverride = string.Empty;
            _lastControlProbeUtc = DateTime.MinValue;
            _control = SentinelControlState.Unknown;
            Wake();
        }

        /// <summary>Issues Start or Stop, waiting for Sentinel to confirm the target state.</summary>
        /// <param name="start">True for start, false for stop.</param>
        /// <param name="cancellationToken">Caller cancellation, linked with the poller's own.</param>
        public async Task<SentinelCommandOutcome> SendCommandAsync(bool start, CancellationToken cancellationToken) {
            var options = new SentinelCommandOptions {
                Wait = true,
                TimeoutSeconds = SentinelCommandOptions.DefaultTimeoutSeconds,

                // A panel button is a person asking for control back, not a sequence step
                // that must know the final state before it unwinds.
                CancellationBehaviour = SentinelCancellation.AbandonRequest,
            };

            using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, _cts.Token);

            try {
                SentinelControlResult result = start
                    ? await _client.StartAsync(options, linked.Token).ConfigureAwait(false)
                    : await _client.StopAsync(options, linked.Token).ConfigureAwait(false);

                // Force the next poll to re-read state rather than showing the pre-command
                // capture state for another period.
                _lastControlProbeUtc = DateTime.MinValue;
                Wake();

                return new SentinelCommandOutcome {
                    Succeeded = result.IsSuccess,
                    Message = result.Message.Length > 0 ? result.Message : result.ToString(),
                };
            } catch (SentinelCommandAbandonedException ex) {
                return new SentinelCommandOutcome {
                    Succeeded = false,
                    Message = ex.Message,
                    Advice = "The command may still have taken effect. Check Sentinel's state before retrying.",
                };
            } catch (SentinelException ex) {
                ApplyControlFailure(ex);
                Wake();
                return new SentinelCommandOutcome {
                    Succeeded = false,
                    Message = ex.Message,
                    Advice = ex.OperatorAdvice,
                };
            } catch (OperationCanceledException) {
                return new SentinelCommandOutcome {
                    Succeeded = false,
                    Message = "The command was cancelled.",
                };
            } catch (Exception ex) {
                return new SentinelCommandOutcome {
                    Succeeded = false,
                    Message = $"The command failed unexpectedly ({ex.GetType().Name}).",
                };
            }
        }

        /// <summary>Stops the loop and releases the HTTP client.</summary>
        public void Dispose() {
            if (_disposed) {
                return;
            }

            _disposed = true;

            try {
                _cts.Cancel();
            } catch (ObjectDisposedException) {
            }

            // Never block the UI thread on the loop: hand teardown to the loop's own
            // continuation instead, so a request still on the wire finishes unwinding
            // before the client goes away.
            Task? loop = _loop;
            if (loop is null) {
                ReleaseResources();
            } else {
                loop.ContinueWith(_ => ReleaseResources(), TaskScheduler.Default);
            }
        }

        private void ReleaseResources() {
            SentinelClient[] clients;
            lock (_clientGate) {
                clients = new SentinelClient[_retiredClients.Count + 1];
                _retiredClients.CopyTo(clients);
                clients[_retiredClients.Count] = _client;
                _retiredClients.Clear();
            }

            foreach (SentinelClient client in clients) {
                try {
                    client.Dispose();
                } catch (Exception) {
                }
            }

            try {
                _cts.Dispose();
            } catch (Exception) {
            }

            try {
                _wake.Dispose();
            } catch (Exception) {
            }
        }

        private void Wake() {
            if (_disposed) {
                return;
            }

            try {
                if (_wake.CurrentCount == 0) {
                    _wake.Release();
                }
            } catch (SemaphoreFullException) {
                // Raced with another waker; the loop is already about to run.
            } catch (ObjectDisposedException) {
            }
        }

        private async Task RunAsync(CancellationToken cancellationToken) {
            while (!cancellationToken.IsCancellationRequested) {
                TimeSpan wait = HiddenIdle;

                if (_visible) {
                    try {
                        await PollOnceAsync(cancellationToken).ConfigureAwait(false);
                    } catch (OperationCanceledException) {
                        break;
                    } catch (Exception ex) {
                        // PollOnceAsync is supposed to absorb everything itself; if it
                        // did not, the loop still has to survive.
                        Emit(FaultSnapshot(ex));
                    }

                    wait = Interval;
                }

                try {
                    await _wake.WaitAsync(wait, cancellationToken).ConfigureAwait(false);
                } catch (OperationCanceledException) {
                    break;
                } catch (ObjectDisposedException) {
                    break;
                }
            }
        }

        /// <summary>
        /// Picks up an edited base URL override, rebuilding the client when it changed.
        /// </summary>
        /// <remarks>Poll thread only.</remarks>
        private void RefreshOverride() {
            string raw;
            try {
                raw = (_overrideSource() ?? string.Empty).Trim();
            } catch (Exception) {
                // A settings read that faults must not stop the panel updating; keep
                // whatever endpoint is already in use.
                return;
            }

            if (string.Equals(raw, _appliedOverride, StringComparison.Ordinal)) {
                return;
            }

            _appliedOverride = raw;

            if (raw.Length == 0) {
                // Back to discovery from Sentinel's own config.json.
                _overrideProblem = string.Empty;
                _activeOverrideUrl = string.Empty;
                SwapClient(_baseOverrides);
                return;
            }

            SentinelEndpointOverride parsed = SentinelEndpointOverride.Parse(raw);
            if (!parsed.IsValid) {
                // Deliberately no client swap and no request: a bad override is a
                // configuration fault, and letting it reach the socket would report it
                // as an unreachable host and send the operator after the wrong thing.
                _overrideProblem = parsed.Problem;
                _activeOverrideUrl = string.Empty;
                return;
            }

            _overrideProblem = string.Empty;
            _activeOverrideUrl = parsed.BaseUrl;

            SwapClient(new SentinelConfigOverrides {
                BaseUrl = parsed.BaseUrl,
                Token = _baseOverrides.Token,
                ConfigPath = _baseOverrides.ConfigPath,
                ControlPath = _baseOverrides.ControlPath,
                StatusPath = _baseOverrides.StatusPath,
                ImagePath = _baseOverrides.ImagePath,
            });
        }

        private void SwapClient(SentinelConfigOverrides overrides) {
            var replacement = new SentinelClient(new SentinelConfigProvider(overrides));

            lock (_clientGate) {
                // Retired rather than disposed: a Start/Stop issued moments ago may still
                // be on the wire holding the old client, and disposing under it would
                // turn a command that succeeded into an ObjectDisposedException. The list
                // is bounded by how often a person edits a textbox.
                _retiredClients.Add(_client);
                _client = replacement;
            }

            // The new endpoint's frames have nothing to do with the old one's, so the
            // ETag, the cached frame and the age carried across 304s are all void.
            _etag = null;
            _frame = null;
            _imageName = string.Empty;
            _noImageYet = false;
            _lastKnownAge = null;
            _lastKnownStale = false;
            _staleThresholdSeconds = null;
            _control = SentinelControlState.Unknown;
            _controlMessage = string.Empty;
            _controlAdvice = string.Empty;
            _lastControlProbeUtc = DateTime.MinValue;
        }

        private async Task PollOnceAsync(CancellationToken cancellationToken) {
            RefreshOverride();

            if (_overrideProblem.Length > 0) {
                Emit(OverrideProblemSnapshot());
                return;
            }

            SentinelConfig config = _client.Configuration;

            SentinelLinkState link = SentinelLinkState.Connected;
            string linkMessage = $"Connected to {config.BaseUrl}";
            string linkAdvice = string.Empty;

            void Fail(SentinelLinkState state, string message, string advice) {
                if (link != SentinelLinkState.Connected) {
                    return;
                }

                link = state;
                linkMessage = message;
                linkAdvice = advice;
            }

            _imageError = null;

            // Tracked separately from `link`: reaching Sentinel at all is what decides
            // whether the control probe is worth attempting, and /latest failing on its
            // own says nothing about the control endpoint.
            bool reachedSentinel = false;

            try {
                await FetchImageAsync(cancellationToken).ConfigureAwait(false);
                reachedSentinel = true;
            } catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) {
                throw;
            } catch (SentinelException ex) {
                Fail(LinkStateFor(ex), ex.Message, ex.OperatorAdvice);
            } catch (Exception ex) {
                Fail(SentinelLinkState.Faulted, $"Could not read the latest frame ({ex.GetType().Name}).", string.Empty);
            }

            SentinelStatus? status = null;
            try {
                status = await _client.GetStatusAsync(cancellationToken).ConfigureAwait(false);
                reachedSentinel = true;
            } catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) {
                throw;
            } catch (SentinelException ex) {
                Fail(LinkStateFor(ex), ex.Message, ex.OperatorAdvice);
            } catch (Exception ex) {
                Fail(SentinelLinkState.Faulted, $"Could not read Sentinel's status ({ex.GetType().Name}).", string.Empty);
            }

            if (status is not null) {
                // /status carries the server's own verdict on age and staleness, which
                // beats anything derived locally — and unlike the image headers it is
                // present on every poll, not only when the frame changed.
                if (status.ImageAgeSeconds is int age) {
                    _lastKnownAge = age;
                    _lastKnownAgeAtUtc = DateTime.UtcNow;
                    _lastKnownStale = status.ImageStale;
                }

                if (status.StaleThresholdSeconds > 0) {
                    _staleThresholdSeconds = status.StaleThresholdSeconds;
                }
            }

            // The local half of the control verdict costs no request, so it runs even
            // when Sentinel is unreachable — that is precisely when an operator needs
            // to be told the config was never found.
            if (!EvaluateLocalControl(config) && reachedSentinel) {
                // Gated on having reached Sentinel rather than on `link`, which an image
                // decode or /latest failure downgrades. Skipping the probe there left
                // _control stuck at Unknown, which greys Start/Stop indefinitely.
                await ProbeControlAsync(cancellationToken).ConfigureAwait(false);
            }

            if (link == SentinelLinkState.Unreachable &&
                config.Status is SentinelConfigStatus.ConfigNotFound or SentinelConfigStatus.ConfigUnreadable) {
                // Without this the panel blames the network for what is really a
                // missing config.json: the client falls back to 127.0.0.1:8080 and the
                // only symptom is a connection refused on a port nobody chose.
                link = SentinelLinkState.Misconfigured;
                linkMessage = config.ProblemDescription;
                linkAdvice = $"Tried {config.BaseUrl}.";
            }

            if (_imageError is { Length: > 0 } decodeError) {
                // Reaching Sentinel and failing to render what it sent is its own
                // fault state; without this it would show as a frozen last-good frame.
                Fail(SentinelLinkState.Faulted, decodeError, string.Empty);
            }

            Emit(BuildSnapshot(config, link, linkMessage, linkAdvice, status));
        }

        private async Task FetchImageAsync(CancellationToken cancellationToken) {
            SentinelImageResult image = await _client
                .TryGetLatestImageAsync(_etag, cancellationToken)
                .ConfigureAwait(false);

            if (image.NoImageYet) {
                _noImageYet = true;
                _frame = null;
                _etag = null;
                _imageName = string.Empty;
                _lastKnownAge = null;
                _lastKnownStale = false;
                return;
            }

            _noImageYet = false;

            if (image.Unchanged) {
                // 304: keep the frame, the age and the stale flag we already had. The
                // response carries none of them, and treating that absence as "fresh"
                // is how an hours-old frame ends up presented as current.
                _etag = image.ETag ?? _etag;
                return;
            }

            if (image.Data is null) {
                return;
            }

            BitmapSource? decoded = SentinelImageDecoder.TryDecode(image.Data, out string? error);
            _imageError = error;

            if (decoded is not null) {
                _frame = decoded;
            }

            _etag = image.ETag;
            _lastKnownAge = image.AgeSeconds;
            _lastKnownAgeAtUtc = DateTime.UtcNow;
            _lastKnownStale = image.Stale;
        }

        /// <summary>Answers the control question from local config alone, where it can.</summary>
        /// <returns>True when the config already settles it and no request is needed.</returns>
        private bool EvaluateLocalControl(SentinelConfig config) {
            if (config.IsControlUsable) {
                return false;
            }

            _control = config.Status switch {
                SentinelConfigStatus.ControlDisabled => SentinelControlState.Disabled,
                _ => SentinelControlState.NotConfigured,
            };
            _controlMessage = config.ProblemDescription;
            _controlAdvice = string.Empty;
            _lastControlProbeUtc = DateTime.UtcNow;
            return true;
        }

        private async Task ProbeControlAsync(CancellationToken cancellationToken) {
            if (_control == SentinelControlState.Available &&
                DateTime.UtcNow - _lastControlProbeUtc < ControlProbeInterval) {
                return;
            }

            try {
                await _client.GetCaptureStateAsync(cancellationToken).ConfigureAwait(false);
                _control = SentinelControlState.Available;
                _controlMessage = string.Empty;
                _controlAdvice = string.Empty;
            } catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) {
                throw;
            } catch (SentinelException ex) {
                ApplyControlFailure(ex);
            } catch (Exception ex) {
                _control = SentinelControlState.Faulted;
                _controlMessage = $"Capture control could not be checked ({ex.GetType().Name}).";
                _controlAdvice = string.Empty;
            } finally {
                _lastControlProbeUtc = DateTime.UtcNow;
            }
        }

        private void ApplyControlFailure(SentinelException ex) {
            _control = ex switch {
                SentinelUnavailableException u when u.ControlDisabled => SentinelControlState.Disabled,
                SentinelUnavailableException u when u.ControlUnwired => SentinelControlState.Unwired,
                SentinelUnauthorizedException => SentinelControlState.Unauthorized,
                SentinelConfigurationException => SentinelControlState.NotConfigured,
                _ => SentinelControlState.Faulted,
            };

            _controlMessage = ex.Message;
            _controlAdvice = ex.OperatorAdvice;
        }

        private static SentinelLinkState LinkStateFor(SentinelException ex) => ex switch {
            SentinelUnreachableException => SentinelLinkState.Unreachable,
            SentinelConfigurationException => SentinelLinkState.Misconfigured,
            _ => SentinelLinkState.Faulted,
        };

        private SentinelPanelSnapshot BuildSnapshot(
            SentinelConfig config,
            SentinelLinkState link,
            string linkMessage,
            string linkAdvice,
            SentinelStatus? status) {

            int? effectiveAge = null;
            if (_lastKnownAge is int known) {
                double elapsed = (DateTime.UtcNow - _lastKnownAgeAtUtc).TotalSeconds;
                effectiveAge = known + (int)Math.Max(0, elapsed);
            }

            bool stale = _lastKnownStale;
            if (effectiveAge is int current && _staleThresholdSeconds is int threshold && threshold > 0) {
                // Re-deriving from the threshold is what lets a frame that has not
                // changed since the last 200 still cross into stale on its own.
                stale = current >= threshold;
            }

            IReadOnlyList<string> reasons = status?.Health?.Reasons is { Count: > 0 } list
                ? list.ToArray()
                : Array.Empty<string>();

            return new SentinelPanelSnapshot {
                Link = link,
                LinkMessage = linkMessage,
                LinkAdvice = linkAdvice,
                Control = _control,
                ControlMessage = _controlMessage,
                ControlAdvice = _controlAdvice,
                Frame = _frame,
                NoImageYet = _noImageYet,
                AgeSeconds = effectiveAge,
                Stale = stale,
                ImageName = status?.LatestImage ?? _imageName,
                HealthStatus = status?.Health?.Status ?? string.Empty,
                HealthReasons = reasons,
                CaptureState = status?.Capture?.State ?? string.Empty,
                CaptureRunning = status?.Capture?.Running ?? false,
                CaptureMode = status?.Capture?.Mode ?? string.Empty,

                // Null rather than zero when Sentinel did not answer: zero would read as
                // a real measurement, and the panel must not invent one.
                UptimeSeconds = status is null ? null : status.UptimeSeconds,
                ImagesServed = status is null ? null : status.ImagesServed,
                IntervalSeconds = status?.Capture?.IntervalSeconds,
                EffectiveIntervalSeconds = status?.Capture?.EffectiveIntervalSeconds,
                LastCaptureAgeSeconds = status?.Capture?.LastCaptureAgeSeconds,
                NextCaptureInSeconds = status?.Capture?.NextCaptureInSeconds,
                RecoveryInProgress = status?.Capture?.Recovery?.InProgress ?? false,
                RecoveryAttempts = status?.Capture?.Recovery?.Attempts ?? 0,
                RecoveryUnrecoverable = status?.Capture?.Recovery?.Unrecoverable ?? false,
                Endpoint = config.BaseUrl,
                EndpointIsOverride = _activeOverrideUrl.Length > 0,
            };
        }

        /// <summary>State for an override the operator has typed but that cannot be used.</summary>
        private SentinelPanelSnapshot OverrideProblemSnapshot() => new() {
            Link = SentinelLinkState.Misconfigured,
            LinkMessage = _overrideProblem,
            LinkAdvice = "Clear the Sentinel base URL override in the plugin options, "
                + "or enter a full address such as http://127.0.0.1:8080.",
            Control = SentinelControlState.NotConfigured,
            ControlMessage = "Fix or clear the base URL override first.",
            Endpoint = _appliedOverride,
            EndpointIsOverride = true,
        };

        private SentinelPanelSnapshot FaultSnapshot(Exception ex) => new() {
            Link = SentinelLinkState.Faulted,
            LinkMessage = $"The Sentinel panel hit an unexpected error ({ex.GetType().Name}).",
            LinkAdvice = "Check NINA's log for detail.",
            Control = _control,
            ControlMessage = _controlMessage,
            ControlAdvice = _controlAdvice,
            Frame = _frame,
        };

        private void Emit(SentinelPanelSnapshot snapshot) {
            try {
                SnapshotReady?.Invoke(snapshot);
            } catch (Exception) {
                // A subscriber's failure must not take the loop down with it.
            }
        }
    }
}

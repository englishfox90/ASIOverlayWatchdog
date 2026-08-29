#nullable enable
using System;
using System.Globalization;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace PFRSentinel.Nina.Client;

/// <summary>
/// Client for PFR Sentinel's HTTP API: capture control, status, and the latest
/// frame.
/// </summary>
/// <remarks>
/// <para>
/// Behaviour mirrors <c>scripts/nina/Invoke-SentinelCapture.ps1</c>, the
/// reference implementation, so both integration paths behave identically and
/// give operators the same advice.
/// </para>
/// <para><b>Design notes that are load-bearing, not stylistic:</b></para>
/// <list type="bullet">
/// <item>
/// <description>
/// <see cref="HttpClient.Timeout"/> is set to <see cref="Timeout.InfiniteTimeSpan"/>
/// and every request gets an explicit budget instead. The default 100s would
/// silently kill a legitimate <c>wait:true, timeout:120</c> call, and the
/// resulting <see cref="TaskCanceledException"/> is indistinguishable from a
/// user cancellation. With the budget on our own linked token we always know
/// which of the two happened.
/// </description>
/// </item>
/// <item>
/// <description>
/// <see cref="HttpResponseMessage.EnsureSuccessStatusCode"/> is never called.
/// Sentinel puts the real cause in the body of a non-2xx ("No ZWO cameras
/// detected", plus a machine-readable <c>code</c>), and that method throws it
/// away.
/// </description>
/// </item>
/// <item>
/// <description>
/// Reads are serialised through a semaphore. Sentinel's web server is
/// thread-per-connection HTTP/1.0 with unbounded thread spawning, so a 3s poll
/// timer that fires while the previous poll is still in flight must not stack.
/// </description>
/// </item>
/// <item>
/// <description>
/// The token is never logged, never put in a URL, and never included in an
/// exception message.
/// </description>
/// </item>
/// </list>
/// </remarks>
public sealed class SentinelClient : IDisposable
{
    private readonly SentinelConfigProvider _config;
    private readonly HttpClient _http;
    private readonly bool _ownsHttpClient;

    // One in-flight read at a time. Control commands are excluded on purpose: a
    // wait:true Start can hold the wire for minutes, and a dockable panel's
    // image poll must not be blocked behind it.
    private readonly SemaphoreSlim _readGate = new(1, 1);

    private bool _disposed;

    /// <summary>Creates a client over a configuration provider.</summary>
    /// <param name="config">Configuration source. Reloaded on a 401.</param>
    /// <param name="handler">Optional handler, for tests. Null uses the default.</param>
    /// <param name="disposeHandler">Whether disposing this client disposes <paramref name="handler"/>.</param>
    public SentinelClient(SentinelConfigProvider config, HttpMessageHandler? handler = null, bool disposeHandler = true)
    {
        _config = config ?? throw new ArgumentNullException(nameof(config));

        _http = handler is null ? new HttpClient() : new HttpClient(handler, disposeHandler);
        _ownsHttpClient = true;

        // See the class remarks: the per-request budget replaces this entirely.
        _http.Timeout = Timeout.InfiniteTimeSpan;

        // Sentinel is HTTP/1.0 and closes every connection, so there is no
        // keep-alive to negotiate and no 100-continue round trip worth paying
        // for on a 40-byte body.
        _http.DefaultRequestHeaders.ExpectContinue = false;
        _http.DefaultRequestHeaders.UserAgent.ParseAdd("PFRSentinel-NINA/1.0");
    }

    /// <summary>Convenience constructor that discovers configuration itself.</summary>
    public SentinelClient(SentinelConfigOverrides? overrides = null)
        : this(new SentinelConfigProvider(overrides))
    {
    }

    /// <summary>
    /// Headroom added to the server's own wait before the client gives up.
    /// </summary>
    /// <remarks>
    /// The server answers a 504 at exactly its own timeout; without slack we
    /// would abandon the socket a fraction before that answer arrives and turn a
    /// perfectly diagnostic "timed out waiting for capture" into "no reply".
    /// 15s matches the PowerShell helper.
    /// </remarks>
    public TimeSpan CommandTimeoutMargin { get; set; } = TimeSpan.FromSeconds(15);

    /// <summary>Budget for a non-waiting request: status, capture state, image, <c>wait:false</c>.</summary>
    public TimeSpan ReadTimeout { get; set; } = TimeSpan.FromSeconds(20);

    /// <summary>The configuration currently in use. Never contains a logged token.</summary>
    public SentinelConfig Configuration => _config.Current;

    /// <summary>Re-reads Sentinel's config.json, picking up a regenerated token.</summary>
    public SentinelConfig ReloadConfiguration() => _config.Reload();

    /// <summary>
    /// Starts capture in Sentinel's configured mode.
    /// </summary>
    /// <param name="options">Wait/timeout/cancellation behaviour. Null uses the defaults (wait, 30s).</param>
    /// <param name="cancellationToken">Caller cancellation. See <see cref="SentinelCancellation"/>.</param>
    /// <returns>
    /// The control result for any status that carries one — 2xx, 500, or 504.
    /// Call <see cref="SentinelControlResult.EnsureSucceeded"/> to convert a
    /// 500/504 into an exception.
    /// </returns>
    /// <remarks>
    /// Idempotent: starting an already-running capture returns HTTP 200 with
    /// <c>result: already_running</c>, <c>issued: false</c>, <c>changed: false</c>.
    /// That is a success — do not treat the false flags as a failure.
    /// </remarks>
    /// <exception cref="SentinelConfigurationException">Control is not configured locally.</exception>
    /// <exception cref="SentinelUnauthorizedException">The token was rejected, twice.</exception>
    /// <exception cref="SentinelUnavailableException">Control is disabled or unwired on the server.</exception>
    /// <exception cref="SentinelUnreachableException">Sentinel did not answer.</exception>
    /// <exception cref="SentinelTimeoutException">The client's own budget expired.</exception>
    /// <exception cref="SentinelCommandAbandonedException">The caller cancelled; the command may still have taken effect.</exception>
    public Task<SentinelControlResult> StartAsync(
        SentinelCommandOptions? options = null,
        CancellationToken cancellationToken = default) =>
        SendCommandAsync("start", options, cancellationToken);

    /// <summary>
    /// Stops capture.
    /// </summary>
    /// <param name="options">Wait/timeout/cancellation behaviour. Null uses the defaults (wait, 30s).</param>
    /// <param name="cancellationToken">Caller cancellation. See <see cref="SentinelCancellation"/>.</param>
    /// <returns>
    /// The control result for any status that carries one — 2xx, 500, or 504.
    /// </returns>
    /// <remarks>
    /// Idempotent: stopping an already-stopped capture returns HTTP 200 with
    /// <c>result: already_stopped</c>. An aborting sequence may fire this twice.
    /// </remarks>
    /// <exception cref="SentinelConfigurationException">Control is not configured locally.</exception>
    /// <exception cref="SentinelUnauthorizedException">The token was rejected, twice.</exception>
    /// <exception cref="SentinelUnavailableException">Control is disabled or unwired on the server.</exception>
    /// <exception cref="SentinelUnreachableException">Sentinel did not answer.</exception>
    /// <exception cref="SentinelTimeoutException">The client's own budget expired.</exception>
    /// <exception cref="SentinelCommandAbandonedException">The caller cancelled; the command may still have taken effect.</exception>
    public Task<SentinelControlResult> StopAsync(
        SentinelCommandOptions? options = null,
        CancellationToken cancellationToken = default) =>
        SendCommandAsync("stop", options, cancellationToken);

    /// <summary>
    /// Reads the current capture and health state from <c>GET &lt;control_path&gt;</c>.
    /// </summary>
    /// <remarks>
    /// Authenticated, so this doubles as a reachability-and-credentials probe —
    /// which is what a NINA sequence item's <c>Validate()</c> wants, since it
    /// proves the token before the night starts without mutating anything.
    /// </remarks>
    public async Task<SentinelCaptureState> GetCaptureStateAsync(CancellationToken cancellationToken = default)
    {
        SentinelConfig config = RequireControlConfig();

        await _readGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            using HttpResponseMessage response = await SendWithTokenRefreshAsync(
                cfg => Authorised(new HttpRequestMessage(HttpMethod.Get, cfg.CaptureStateUri), cfg),
                config, ReadTimeout, honourCallerCancellation: true, cancellationToken).ConfigureAwait(false);

            string body = await ReadBodyAsync(response).ConfigureAwait(false);
            if (!IsSuccess(response.StatusCode))
            {
                throw MapErrorResponse(response.StatusCode, body, config);
            }

            return SentinelJson.Deserialize<SentinelCaptureState>(body, "capture state");
        }
        finally
        {
            _readGate.Release();
        }
    }

    /// <summary>
    /// Reads <c>GET /status</c> — the unauthenticated server overview.
    /// </summary>
    /// <remarks>
    /// Needs no token, so it still works when the control API is switched off.
    /// Use it for the panel's health line; use
    /// <see cref="GetCaptureStateAsync"/> when you also want to prove the token.
    /// </remarks>
    public async Task<SentinelStatus> GetStatusAsync(CancellationToken cancellationToken = default)
    {
        SentinelConfig config = RequireEndpoint();

        await _readGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            using HttpResponseMessage response = await SendOnceAsync(
                new HttpRequestMessage(HttpMethod.Get, config.StatusUri),
                ReadTimeout, honourCallerCancellation: true, command: null,
                config, cancellationToken).ConfigureAwait(false);

            string body = await ReadBodyAsync(response).ConfigureAwait(false);
            if (!IsSuccess(response.StatusCode))
            {
                throw MapErrorResponse(response.StatusCode, body, config);
            }

            return SentinelJson.Deserialize<SentinelStatus>(body, "status");
        }
        finally
        {
            _readGate.Release();
        }
    }

    /// <summary>
    /// Conditionally fetches the latest frame from <c>GET /latest</c>.
    /// </summary>
    /// <param name="knownETag">
    /// The <see cref="SentinelImageResult.ETag"/> from the previous successful
    /// fetch, or null to force a full download.
    /// </param>
    /// <param name="cancellationToken">Caller cancellation.</param>
    /// <returns>
    /// A result that is one of: the image bytes,
    /// <see cref="SentinelImageResult.Unchanged"/> (HTTP 304), or
    /// <see cref="SentinelImageResult.NoImageYet"/> (HTTP 404). None of the
    /// three is an error.
    /// </returns>
    /// <remarks>
    /// <para>
    /// Sending <c>If-None-Match</c> makes idle polling nearly free — the server
    /// answers 304 with no body while the frame is unchanged.
    /// </para>
    /// <para>
    /// The ETag is added with <c>TryAddWithoutValidation</c> on purpose.
    /// Sentinel emits a bare MD5 hex digest with no surrounding quotes, which
    /// <see cref="EntityTagHeaderValue"/> rejects as malformed; and the server
    /// compares the header with <c>==</c>, so a client that "helpfully" adds the
    /// quotes never gets a 304 and silently re-downloads every frame forever.
    /// For the same reason the response ETag is read via
    /// <c>Headers.TryGetValues</c> rather than <c>Headers.ETag</c>, which parses
    /// strictly and would hand back null.
    /// </para>
    /// </remarks>
    public async Task<SentinelImageResult> TryGetLatestImageAsync(
        string? knownETag = null,
        CancellationToken cancellationToken = default)
    {
        SentinelConfig config = RequireEndpoint();

        await _readGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            var request = new HttpRequestMessage(HttpMethod.Get, config.ImageUri);
            if (!string.IsNullOrEmpty(knownETag))
            {
                // VERIFY (against a live Sentinel): that a second poll really does
                // get a 304. TryAddWithoutValidation should send the unquoted tag
                // byte-for-byte, but if HttpClient normalises or drops it, this
                // fails silently — every frame re-downloads and nothing errors.
                request.Headers.TryAddWithoutValidation("If-None-Match", knownETag);
            }

            // VERIFY (compiler): non-trailing named arguments. Legal since C# 7.2
            // when each named argument sits in its declared position, which they do.
            using HttpResponseMessage response = await SendOnceAsync(
                request, ReadTimeout, honourCallerCancellation: true, command: null,
                config, cancellationToken).ConfigureAwait(false);

            string? etag = FirstHeader(response, "ETag");

            if (response.StatusCode == HttpStatusCode.NotModified)
            {
                // The 304 path sends only ETag — no age or stale headers — so a
                // caller must keep the age it already had rather than reading
                // "absent" as "fresh".
                return SentinelImageResult.FromUnchanged(etag ?? knownETag);
            }

            if (response.StatusCode == HttpStatusCode.NotFound)
            {
                // Sentinel's "no image available yet" is a plain 404 with an
                // HTML body from BaseHTTPRequestHandler, not a JSON envelope.
                return SentinelImageResult.FromNoImage();
            }

            if (!IsSuccess(response.StatusCode))
            {
                string body = await ReadBodyAsync(response).ConfigureAwait(false);
                throw MapErrorResponse(response.StatusCode, body, config);
            }

            byte[] data = await response.Content.ReadAsByteArrayAsync(CancellationToken.None).ConfigureAwait(false);

            // VERIFY: the server sends this on every 200, so far as the source
            // shows. Absence is tolerated (AgeSeconds stays null) rather than
            // assumed impossible.
            int? age = null;
            string? ageHeader = FirstHeader(response, "X-PFR-Image-Age-Seconds");
            if (ageHeader is not null &&
                int.TryParse(ageHeader, NumberStyles.Integer, CultureInfo.InvariantCulture, out int parsedAge))
            {
                age = parsedAge;
            }

            // The server omits the header entirely when the image is fresh; it
            // never sends "false".
            bool stale = string.Equals(FirstHeader(response, "X-PFR-Image-Stale"), "true", StringComparison.OrdinalIgnoreCase);

            return SentinelImageResult.FromImage(data, response.Content.Headers.ContentType?.MediaType, etag, age, stale);
        }
        finally
        {
            _readGate.Release();
        }
    }

    private async Task<SentinelControlResult> SendCommandAsync(
        string command,
        SentinelCommandOptions? options,
        CancellationToken cancellationToken)
    {
        options ??= new SentinelCommandOptions();
        options.Validate();

        SentinelConfig config = RequireControlConfig();

        TimeSpan budget = options.Wait
            ? TimeSpan.FromSeconds(options.TimeoutSeconds) + CommandTimeoutMargin
            : ReadTimeout;

        bool honourCancellation = options.CancellationBehaviour == SentinelCancellation.AbandonRequest;

        using HttpResponseMessage response = await SendWithTokenRefreshAsync(
            cfg => BuildCommandRequest(cfg, command, options),
            config, budget, honourCancellation, cancellationToken, command).ConfigureAwait(false);

        string body = await ReadBodyAsync(response).ConfigureAwait(false);
        int status = (int)response.StatusCode;

        // 200, 500 and 504 all carry a complete control body. 500 is ambiguous:
        // the unhandled-exception path in web_output.do_POST answers with an
        // error envelope instead, so decide by shape (a "result" field) rather
        // than by status.
        if (IsSuccess(response.StatusCode) || status is 500 or 504)
        {
            SentinelControlResult? result = TryParseControlResult(body);
            if (result is not null)
            {
                result.HttpStatus = status;
                return result;
            }

            if (IsSuccess(response.StatusCode))
            {
                throw new SentinelException(SentinelErrorKind.Protocol,
                    $"Sentinel returned HTTP {status} for '{command}' without a control result body.");
            }
        }

        throw MapErrorResponse(response.StatusCode, body, config);
    }

    private HttpRequestMessage BuildCommandRequest(SentinelConfig config, string command, SentinelCommandOptions options)
    {
        Uri uri = command == "start" ? config.StartUri : config.StopUri;

        // Hand-built rather than serialised: two scalars, and it keeps the
        // payload obviously identical to what the API contract documents.
        string json = string.Concat(
            "{\"wait\":", options.Wait ? "true" : "false",
            ",\"timeout\":", options.TimeoutSeconds.ToString(CultureInfo.InvariantCulture),
            "}");

        var request = new HttpRequestMessage(HttpMethod.Post, uri)
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json"),
        };

        return Authorised(request, config);
    }

    private static HttpRequestMessage Authorised(HttpRequestMessage request, SentinelConfig config)
    {
        if (config.HasToken)
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", config.Token);
        }

        // The Host header HttpClient derives from the URI authority (e.g.
        // "127.0.0.1:8080") is what Sentinel's anti-rebinding allow-list checks;
        // it strips the port and requires loopback or an explicitly allow-listed
        // name. Never override it.
        return request;
    }

    /// <summary>
    /// Sends a request and, on a 401, re-reads Sentinel's config once before
    /// retrying.
    /// </summary>
    /// <remarks>
    /// <para>
    /// A 401 is deliberately identical for a missing, malformed, or wrong token,
    /// so the status cannot tell us what went wrong. But this client reads the
    /// token out of Sentinel's own config.json, which rules out "missing" and
    /// "malformed" — leaving "the operator regenerated it in the UI while we
    /// held the old one" as by far the most likely cause. Re-reading and
    /// retrying turns a confusing auth failure into a non-event.
    /// </para>
    /// <para>
    /// The retry is skipped when the token is pinned by an override (a reload
    /// cannot change it) or when the reloaded token is byte-identical (the
    /// answer is deterministic, so a second call only doubles the delay before
    /// the operator sees the real problem).
    /// </para>
    /// <para>
    /// Retrying a POST is safe here specifically because a 401 is rejected in
    /// <c>web_control.authorize</c> before any command reaches the app, and
    /// because both commands are idempotent by contract anyway.
    /// </para>
    /// </remarks>
    private async Task<HttpResponseMessage> SendWithTokenRefreshAsync(
        Func<SentinelConfig, HttpRequestMessage> requestFactory,
        SentinelConfig config,
        TimeSpan budget,
        bool honourCallerCancellation,
        CancellationToken cancellationToken,
        string? command = null)
    {
        HttpResponseMessage response = await SendOnceAsync(
            requestFactory(config), budget, honourCallerCancellation, command, config, cancellationToken)
            .ConfigureAwait(false);

        if (response.StatusCode != HttpStatusCode.Unauthorized || _config.HasTokenOverride)
        {
            return response;
        }

        SentinelConfig refreshed = _config.Reload();
        if (!refreshed.HasToken || string.Equals(refreshed.Token, config.Token, StringComparison.Ordinal))
        {
            return response;
        }

        response.Dispose();

        // The retry gets a fresh budget rather than the remainder of the first.
        // A 401 comes back in milliseconds, so the worst case is a negligible
        // overshoot, and carrying a partly-spent budget into a wait:true command
        // could truncate a legitimate wait.
        return await SendOnceAsync(
            requestFactory(refreshed), budget, honourCallerCancellation, command, refreshed, cancellationToken)
            .ConfigureAwait(false);
    }

    private async Task<HttpResponseMessage> SendOnceAsync(
        HttpRequestMessage request,
        TimeSpan budget,
        bool honourCallerCancellation,
        string? command,
        SentinelConfig config,
        CancellationToken cancellationToken)
    {
        using var budgetSource = new CancellationTokenSource(budget);

        // Linked either way, so the disposal shape is uniform. When the caller's
        // token is deliberately not honoured (SentinelCancellation.CompleteRequest)
        // it simply is not part of the link.
        using CancellationTokenSource linked = honourCallerCancellation
            ? CancellationTokenSource.CreateLinkedTokenSource(budgetSource.Token, cancellationToken)
            : CancellationTokenSource.CreateLinkedTokenSource(budgetSource.Token);

        try
        {
            // ResponseContentRead (the default) buffers the body before this
            // returns, so a stalled body transfer is covered by the same budget
            // as the headers. Sentinel's payloads are small enough that
            // buffering costs nothing.
            return await _http.SendAsync(request, HttpCompletionOption.ResponseContentRead, linked.Token)
                .ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (honourCallerCancellation && cancellationToken.IsCancellationRequested)
        {
            // Genuine caller cancellation. Distinguishable from the budget only
            // because the budget lives on a token of our own.
            throw new SentinelCommandAbandonedException(command ?? "request", cancellationToken);
        }
        catch (OperationCanceledException ex)
        {
            throw new SentinelTimeoutException(budget, ex);
        }
        catch (HttpRequestException ex)
        {
            throw new SentinelUnreachableException(config.BaseUrl, ex);
        }
        finally
        {
            request.Dispose();
        }
    }

    private static async Task<string> ReadBodyAsync(HttpResponseMessage response)
    {
        try
        {
            // Already buffered by ResponseContentRead, so no token is needed and
            // none is passed — cancelling here would only corrupt an answer we
            // already hold.
            return await response.Content.ReadAsStringAsync(CancellationToken.None).ConfigureAwait(false);
        }
        catch (Exception)
        {
            return string.Empty;
        }
    }

    private static bool IsSuccess(HttpStatusCode status) => (int)status is >= 200 and < 300;

    private static string? FirstHeader(HttpResponseMessage response, string name)
    {
        if (response.Headers.TryGetValues(name, out var values))
        {
            foreach (string value in values)
            {
                return value;
            }
        }

        return null;
    }

    private static SentinelControlResult? TryParseControlResult(string body)
    {
        if (string.IsNullOrWhiteSpace(body))
        {
            return null;
        }

        try
        {
            using JsonDocument document = JsonDocument.Parse(body);
            if (document.RootElement.ValueKind != JsonValueKind.Object ||
                !document.RootElement.TryGetProperty("result", out _))
            {
                return null;
            }
        }
        catch (JsonException)
        {
            return null;
        }

        try
        {
            return JsonSerializer.Deserialize<SentinelControlResult>(body, SentinelJson.Options);
        }
        catch (JsonException)
        {
            return null;
        }
    }

    /// <summary>Turns a non-2xx response into the most specific exception available.</summary>
    /// <remarks>
    /// The body is parsed first, always. Sentinel's error envelope is
    /// <c>{error, status, code}</c>, and <c>code</c> is the only thing that
    /// separates the two causes of a 503 — which need opposite advice.
    /// </remarks>
    private static SentinelException MapErrorResponse(HttpStatusCode statusCode, string body, SentinelConfig config)
    {
        (string? message, string? code) = ParseErrorBody(body);
        int status = (int)statusCode;

        return status switch
        {
            401 => new SentinelUnauthorizedException(code),
            403 => new SentinelForbiddenException(message, code),
            400 or 413 => new SentinelException(
                SentinelErrorKind.BadRequest,
                message ?? $"Sentinel rejected the request (HTTP {status}).",
                code, statusCode),
            404 => new SentinelException(
                SentinelErrorKind.Protocol,
                message ?? "Sentinel has no endpoint at the configured path (HTTP 404). Check the paths in Sentinel's Output settings.",
                code, statusCode),
            503 => new SentinelUnavailableException(message, code),
            // Reached only when the body was NOT a control result — i.e. the
            // unhandled-exception path in web_output.do_POST, or a 504 with no
            // body at all. A control body is handled by the caller.
            500 => new SentinelException(
                SentinelErrorKind.CommandFailed,
                message ?? "Sentinel hit an internal error handling the request.",
                code, statusCode),
            504 => new SentinelException(
                SentinelErrorKind.WaitTimedOut,
                message ?? "Sentinel timed out waiting for capture to reach the requested state.",
                code, statusCode),
            _ => new SentinelException(
                SentinelErrorKind.Protocol,
                message ?? $"Unexpected HTTP {status} from Sentinel at {config.BaseUrl}.",
                code, statusCode),
        };
    }

    private static (string? Message, string? Code) ParseErrorBody(string body)
    {
        if (string.IsNullOrWhiteSpace(body))
        {
            return (null, null);
        }

        try
        {
            using JsonDocument document = JsonDocument.Parse(body);
            if (document.RootElement.ValueKind != JsonValueKind.Object)
            {
                return (null, null);
            }

            string? message = null;
            // A control body uses "message"; an error envelope uses "error".
            if (document.RootElement.TryGetProperty("message", out JsonElement messageElement) &&
                messageElement.ValueKind == JsonValueKind.String)
            {
                message = messageElement.GetString();
            }
            else if (document.RootElement.TryGetProperty("error", out JsonElement errorElement) &&
                     errorElement.ValueKind == JsonValueKind.String)
            {
                message = errorElement.GetString();
            }

            string? code = null;
            if (document.RootElement.TryGetProperty("code", out JsonElement codeElement) &&
                codeElement.ValueKind == JsonValueKind.String)
            {
                code = codeElement.GetString();
            }

            return (message, code);
        }
        catch (JsonException)
        {
            // A 404 from BaseHTTPRequestHandler is HTML, not JSON. Not an error.
            return (null, null);
        }
    }

    private SentinelConfig RequireControlConfig()
    {
        // VERIFY (compiler): ObjectDisposedException.ThrowIf is .NET 7+. Fine on
        // net8.0-windows; it is the only API here newer than .NET 6.
        ObjectDisposedException.ThrowIf(_disposed, this);

        SentinelConfig config = _config.Current;
        if (!config.IsControlUsable)
        {
            throw new SentinelConfigurationException(config);
        }

        return config;
    }

    private SentinelConfig RequireEndpoint()
    {
        // VERIFY (compiler): ObjectDisposedException.ThrowIf is .NET 7+. Fine on
        // net8.0-windows; it is the only API here newer than .NET 6.
        ObjectDisposedException.ThrowIf(_disposed, this);

        // /status and /latest are unauthenticated, so they must still work when
        // control is switched off — that is exactly the state a panel needs to
        // display and explain.
        return _config.Current;
    }

    /// <summary>Disposes the underlying <see cref="HttpClient"/>.</summary>
    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;

        if (_ownsHttpClient)
        {
            _http.Dispose();
        }

        // _readGate is deliberately not disposed: a poll already inside the gate
        // would hit ObjectDisposedException on its Release, turning an orderly
        // shutdown into a crash. SemaphoreSlim only needs disposal when its
        // AvailableWaitHandle has been used, and this one never touches it.
    }
}

#nullable enable
using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace PFRSentinel.Nina.Client;

/// <summary>
/// Shared JSON settings for every Sentinel payload.
/// </summary>
/// <remarks>
/// <c>System.Text.Json</c> rather than <c>Newtonsoft.Json</c>: it is in-box for
/// <c>net8.0-windows</c>, so the plugin adds no package that could clash with
/// whatever version NINA has already loaded into the process.
/// </remarks>
internal static class SentinelJson
{
    /// <summary>Options used for every deserialisation in this client.</summary>
    internal static readonly JsonSerializerOptions Options = new()
    {
        PropertyNameCaseInsensitive = true,
        // Sentinel's config is user-editable and some numeric fields have been
        // seen as strings in the wild; be liberal in what we accept.
        NumberHandling = JsonNumberHandling.AllowReadingFromString,
        ReadCommentHandling = JsonCommentHandling.Skip,
    };

    /// <summary>Deserialises, converting any parse failure into a protocol error.</summary>
    internal static T Deserialize<T>(string body, string what) where T : class
    {
        try
        {
            T? parsed = JsonSerializer.Deserialize<T>(body, Options);
            if (parsed is null)
            {
                throw new SentinelException(SentinelErrorKind.Protocol, $"Sentinel returned an empty {what} response.");
            }

            return parsed;
        }
        catch (JsonException ex)
        {
            // The body is not echoed: it is bounded but unbounded in shape, and
            // an error path is not the place to start pasting server output into
            // a NINA sequence log.
            throw new SentinelException(SentinelErrorKind.Protocol,
                $"Sentinel returned a {what} response that could not be parsed.", innerException: ex);
        }
    }
}

/// <summary>
/// The literal <c>result</c> strings from a control response.
/// </summary>
/// <remarks>
/// Mirrors the <c>RESULT_*</c> constants in <c>services/api_control.py</c>.
/// Kept alongside <see cref="SentinelResultKind"/> so an unrecognised future
/// value can still be surfaced verbatim rather than lost to an enum fallback.
/// </remarks>
public static class SentinelResults
{
    /// <summary>Capture was started by this command.</summary>
    public const string Started = "started";

    /// <summary>Capture was stopped by this command.</summary>
    public const string Stopped = "stopped";

    /// <summary>Capture was already running; nothing was issued.</summary>
    public const string AlreadyRunning = "already_running";

    /// <summary>Capture was already stopped; nothing was issued.</summary>
    public const string AlreadyStopped = "already_stopped";

    /// <summary>Command issued with <c>wait:false</c>; the resulting state is unconfirmed.</summary>
    public const string Pending = "pending";

    /// <summary>Command issued, but the target state was not reached before the server's timeout.</summary>
    public const string Timeout = "timeout";

    /// <summary>Capture reported an error while the server waited.</summary>
    public const string Failed = "failed";
}

/// <summary>Strongly typed form of <see cref="SentinelResults"/>.</summary>
public enum SentinelResultKind
{
    /// <summary>A <c>result</c> value this client does not recognise. Read <see cref="SentinelControlResult.Result"/>.</summary>
    Unknown = 0,

    /// <summary><c>started</c> — capture state changed.</summary>
    Started,

    /// <summary><c>stopped</c> — capture state changed.</summary>
    Stopped,

    /// <summary><c>already_running</c> — idempotent no-op, and a success.</summary>
    AlreadyRunning,

    /// <summary><c>already_stopped</c> — idempotent no-op, and a success.</summary>
    AlreadyStopped,

    /// <summary><c>pending</c> — issued without waiting; state unconfirmed.</summary>
    Pending,

    /// <summary><c>timeout</c> — HTTP 504. Issued, but the target state was not reached in time.</summary>
    Timeout,

    /// <summary><c>failed</c> — HTTP 500. Capture reported a real error.</summary>
    Failed,
}

/// <summary>Health roll-up from <c>services/api_status.py</c>.</summary>
public enum SentinelHealthStatus
{
    /// <summary>A <c>health.status</c> value this client does not recognise.</summary>
    Unknown = 0,

    /// <summary><c>ok</c> — capture running and producing fresh frames.</summary>
    Ok,

    /// <summary><c>idle</c> — intentionally not capturing (off, or outside the scheduled window).</summary>
    Idle,

    /// <summary><c>degraded</c> — enabled and running, but frames have stalled.</summary>
    Degraded,

    /// <summary><c>recovering</c> — auto-recovery in progress.</summary>
    Recovering,

    /// <summary><c>error</c> — capture failed, possibly unrecoverably.</summary>
    Error,
}

/// <summary>
/// The body of a <c>POST /capture/start</c> or <c>/capture/stop</c> response.
/// </summary>
/// <remarks>
/// <para>
/// Fields mirror <c>CONTROL_RESULT_FIELDS</c> in <c>services/api_control.py</c>.
/// </para>
/// <para>
/// <b>This type is returned for 500 and 504 as well as 2xx.</b> Those statuses
/// still carry a complete control body — the reason capture failed is in
/// <see cref="Message"/>, and it is far more useful than "check the log". Only
/// the envelope-shaped errors (400/401/403/413/503) throw. Call
/// <see cref="EnsureSucceeded"/> if you would rather have an exception.
/// </para>
/// </remarks>
public sealed class SentinelControlResult
{
    /// <summary>The command that was issued: <c>start</c> or <c>stop</c>.</summary>
    [JsonPropertyName("command")]
    public string Command { get; set; } = string.Empty;

    /// <summary>Raw outcome string. See <see cref="SentinelResults"/>.</summary>
    [JsonPropertyName("result")]
    public string Result { get; set; } = string.Empty;

    /// <summary>Whether capture state actually changed — true only for <c>started</c>/<c>stopped</c>.</summary>
    [JsonPropertyName("changed")]
    public bool Changed { get; set; }

    /// <summary>
    /// Whether a command was handed to the app. False for idempotent no-ops.
    /// </summary>
    /// <remarks>
    /// <c>issued:false, changed:false</c> with HTTP 200 is the normal answer to
    /// "start something already started". It is a success, not a nothing-happened
    /// warning — a sequence that re-runs Start must not treat it as a fault.
    /// </remarks>
    [JsonPropertyName("issued")]
    public bool Issued { get; set; }

    /// <summary>Capture state reached, e.g. <c>capturing</c>, <c>waiting</c>, <c>stopped</c>, <c>error</c>.</summary>
    [JsonPropertyName("state")]
    public string State { get; set; } = string.Empty;

    /// <summary>Whether capture is producing frames.</summary>
    [JsonPropertyName("running")]
    public bool Running { get; set; }

    /// <summary>Whether capture is enabled in the app.</summary>
    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; }

    /// <summary>Whether the request blocked waiting for the target state.</summary>
    [JsonPropertyName("waited")]
    public bool Waited { get; set; }

    /// <summary>Seconds the server spent waiting; 0 when <c>wait</c> was false.</summary>
    [JsonPropertyName("wait_seconds")]
    public double WaitSeconds { get; set; }

    /// <summary>
    /// Human-readable outcome, safe to surface in a UI or a sequence log.
    /// </summary>
    /// <remarks>
    /// On a failure this is the underlying cause verbatim ("No ZWO cameras
    /// detected"), not a generic phrase — render it rather than substituting
    /// your own wording.
    /// </remarks>
    [JsonPropertyName("message")]
    public string Message { get; set; } = string.Empty;

    /// <summary>HTTP status the body arrived with. Set by the client, not by the server.</summary>
    [JsonIgnore]
    public int HttpStatus { get; internal set; }

    /// <summary>Whether the request succeeded — any 2xx, including idempotent no-ops.</summary>
    [JsonIgnore]
    public bool IsSuccess => HttpStatus is >= 200 and < 300;

    /// <summary>Typed form of <see cref="Result"/>.</summary>
    [JsonIgnore]
    public SentinelResultKind Kind => Result switch
    {
        SentinelResults.Started => SentinelResultKind.Started,
        SentinelResults.Stopped => SentinelResultKind.Stopped,
        SentinelResults.AlreadyRunning => SentinelResultKind.AlreadyRunning,
        SentinelResults.AlreadyStopped => SentinelResultKind.AlreadyStopped,
        SentinelResults.Pending => SentinelResultKind.Pending,
        SentinelResults.Timeout => SentinelResultKind.Timeout,
        SentinelResults.Failed => SentinelResultKind.Failed,
        _ => SentinelResultKind.Unknown,
    };

    /// <summary>Throws a <see cref="SentinelException"/> unless this result is a 2xx.</summary>
    /// <remarks>
    /// For a sequence item that should fail the step on anything but success.
    /// A 504 becomes <see cref="SentinelErrorKind.WaitTimedOut"/> and a 500
    /// becomes <see cref="SentinelErrorKind.CommandFailed"/>, matching the exit
    /// codes the PowerShell helper uses for the same two cases.
    /// </remarks>
    public SentinelControlResult EnsureSucceeded()
    {
        if (IsSuccess)
        {
            return this;
        }

        SentinelErrorKind kind = HttpStatus switch
        {
            504 => SentinelErrorKind.WaitTimedOut,
            500 => SentinelErrorKind.CommandFailed,
            _ => SentinelErrorKind.Protocol,
        };

        string message = Message.Length > 0
            ? Message
            : $"Capture command '{Command}' failed (HTTP {HttpStatus}, state '{State}').";

        throw new SentinelException(kind, message, statusCode: (System.Net.HttpStatusCode)HttpStatus);
    }

    /// <summary>Short description for a log line.</summary>
    public override string ToString() =>
        $"{Command} -> {Result} (state={State}, running={Running}, changed={Changed}, http={HttpStatus})";
}

/// <summary>Scheduled-window block of the capture snapshot.</summary>
/// <remarks>
/// VERIFY: these names come from the prose in <c>CAPTURE_FIELDS</c>
/// (<c>services/api_status.py</c>), not from the code that builds the dict. A
/// mismatch degrades to nulls rather than throwing — System.Text.Json ignores
/// unknown members — so check against a real <c>/status</c> payload.
/// </remarks>
public sealed class SentinelSchedule
{
    /// <summary><c>always</c>, <c>gated</c>, or <c>variable</c>.</summary>
    [JsonPropertyName("mode")]
    public string? Mode { get; set; }

    /// <summary>Window start, as configured.</summary>
    [JsonPropertyName("start_time")]
    public string? StartTime { get; set; }

    /// <summary>Window end, as configured.</summary>
    [JsonPropertyName("end_time")]
    public string? EndTime { get; set; }

    /// <summary>Whether the current time falls inside the window.</summary>
    [JsonPropertyName("in_window")]
    public bool? InWindow { get; set; }

    /// <summary>Interval used inside the window, in seconds.</summary>
    [JsonPropertyName("window_interval_seconds")]
    public double? WindowIntervalSeconds { get; set; }
}

/// <summary>Auto-recovery block of the capture snapshot.</summary>
public sealed class SentinelRecovery
{
    /// <summary>Whether a recovery attempt is under way.</summary>
    [JsonPropertyName("in_progress")]
    public bool InProgress { get; set; }

    /// <summary>How many recovery attempts have been made.</summary>
    [JsonPropertyName("attempts")]
    public int Attempts { get; set; }

    /// <summary>Whether the camera is beyond automatic recovery and needs a manual restart.</summary>
    [JsonPropertyName("unrecoverable")]
    public bool Unrecoverable { get; set; }
}

/// <summary>
/// The <c>capture</c> block of <c>/status</c> and <c>GET /capture</c>.
/// </summary>
/// <remarks>Fields mirror <c>CAPTURE_FIELDS</c> in <c>services/api_status.py</c>.</remarks>
public sealed class SentinelCapture
{
    /// <summary>Capture mode: <c>camera</c>, <c>watch</c>, or <c>idle</c>.</summary>
    [JsonPropertyName("mode")]
    public string Mode { get; set; } = "idle";

    /// <summary>Whether capture is currently enabled in the app.</summary>
    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; }

    /// <summary>Whether capture is actively producing frames right now.</summary>
    [JsonPropertyName("running")]
    public bool Running { get; set; }

    /// <summary>
    /// Fine-grained state: <c>capturing</c>, <c>waiting</c>, <c>calibrating</c>,
    /// <c>recovering</c>, <c>outside_window</c>, <c>stopped</c>, <c>error</c>.
    /// </summary>
    /// <remarks>
    /// <c>outside_window</c> counts as started: a scheduled run that is enabled
    /// but waiting for dusk has started, and blocking a sequence until dusk
    /// would be wrong.
    /// </remarks>
    [JsonPropertyName("state")]
    public string State { get; set; } = "stopped";

    /// <summary>Configured seconds between captures (camera mode); null in watch mode.</summary>
    [JsonPropertyName("interval_seconds")]
    public double? IntervalSeconds { get; set; }

    /// <summary>Interval actually in effect now, honouring variable-rate schedules.</summary>
    [JsonPropertyName("effective_interval_seconds")]
    public double? EffectiveIntervalSeconds { get; set; }

    /// <summary>Scheduled-window configuration, or null when no schedule applies.</summary>
    [JsonPropertyName("schedule")]
    public SentinelSchedule? Schedule { get; set; }

    /// <summary>Seconds since the last successful capture, or null if there has been none.</summary>
    [JsonPropertyName("last_capture_age_seconds")]
    public int? LastCaptureAgeSeconds { get; set; }

    /// <summary>Estimated seconds until the next capture; null if not predictable.</summary>
    [JsonPropertyName("next_capture_in_seconds")]
    public int? NextCaptureInSeconds { get; set; }

    /// <summary>Unix timestamp of the next expected capture; null if not predictable.</summary>
    [JsonPropertyName("next_capture_expected_epoch")]
    public double? NextCaptureExpectedEpoch { get; set; }

    /// <summary>Auto-recovery state.</summary>
    [JsonPropertyName("recovery")]
    public SentinelRecovery? Recovery { get; set; }

    /// <summary>Most recent capture error message, or null.</summary>
    [JsonPropertyName("last_error")]
    public string? LastError { get; set; }

    /// <summary>
    /// Unix timestamp of the most recent capture error, or null.
    /// </summary>
    /// <remarks>
    /// Compare this, not <see cref="LastError"/>, to tell a new failure from the
    /// same fault reported again — a repeated fault produces identical text.
    /// </remarks>
    [JsonPropertyName("last_error_epoch")]
    public double? LastErrorEpoch { get; set; }
}

/// <summary>The <c>health</c> block: an overall verdict plus human-readable reasons.</summary>
public sealed class SentinelHealth
{
    /// <summary>Raw status string: <c>ok</c>, <c>idle</c>, <c>degraded</c>, <c>recovering</c>, <c>error</c>.</summary>
    [JsonPropertyName("status")]
    public string Status { get; set; } = string.Empty;

    /// <summary>
    /// Why, in operator-facing English.
    /// </summary>
    /// <remarks>
    /// Already phrased for display ("no new frame for 900s — capture may be
    /// stalled"). Render verbatim; do not reword.
    /// </remarks>
    [JsonPropertyName("reasons")]
    public List<string> Reasons { get; set; } = new();

    /// <summary>Typed form of <see cref="Status"/>.</summary>
    [JsonIgnore]
    public SentinelHealthStatus Kind => Status switch
    {
        "ok" => SentinelHealthStatus.Ok,
        "idle" => SentinelHealthStatus.Idle,
        "degraded" => SentinelHealthStatus.Degraded,
        "recovering" => SentinelHealthStatus.Recovering,
        "error" => SentinelHealthStatus.Error,
        _ => SentinelHealthStatus.Unknown,
    };
}

/// <summary>
/// The body of <c>GET &lt;control_path&gt;</c> — the authenticated alias for the
/// <c>capture</c> and <c>health</c> blocks of <c>/status</c>.
/// </summary>
public sealed class SentinelCaptureState
{
    /// <summary>Current capture state.</summary>
    [JsonPropertyName("capture")]
    public SentinelCapture? Capture { get; set; }

    /// <summary>Current health roll-up.</summary>
    [JsonPropertyName("health")]
    public SentinelHealth? Health { get; set; }

    /// <summary>
    /// Whether a start/stop would actually be accepted right now — i.e. Sentinel
    /// has a capture command handler registered.
    /// </summary>
    /// <remarks>
    /// Lets a caller pre-flight without issuing a command, which is what makes a
    /// NINA sequence's Validate() honest: without it the route checks only the
    /// token, so an unwired Sentinel answers 200 here and fails only when a
    /// command arrives — validating green at dusk and failing at 22:15.
    ///
    /// Null when the server predates the field. Treat null as ready: refusing to
    /// validate against an older Sentinel would be a regression, not a safeguard.
    /// </remarks>
    [JsonPropertyName("control_ready")]
    public bool? ControlReady { get; set; }

    /// <summary>Server-local ISO timestamp of the response.</summary>
    [JsonPropertyName("timestamp")]
    public string? Timestamp { get; set; }
}

/// <summary>
/// The body of <c>GET /status</c> — the unauthenticated server overview.
/// </summary>
/// <remarks>
/// The flat image fields predate the <c>capture</c>/<c>health</c> blocks and are
/// kept for older consumers; prefer <see cref="Health"/> for a verdict.
/// </remarks>
public sealed class SentinelStatus
{
    /// <summary>Server banner, e.g. "PFR Sentinel HTTP Server".</summary>
    [JsonPropertyName("server")]
    public string? Server { get; set; }

    /// <summary>Server run state, e.g. "running".</summary>
    [JsonPropertyName("status")]
    public string? Status { get; set; }

    /// <summary>Seconds since the web server started.</summary>
    [JsonPropertyName("uptime_seconds")]
    public int UptimeSeconds { get; set; }

    /// <summary>How many images the server has served.</summary>
    [JsonPropertyName("images_served")]
    public int ImagesServed { get; set; }

    /// <summary>Bare filename of the latest image. Sentinel scrubs the path deliberately.</summary>
    [JsonPropertyName("latest_image")]
    public string? LatestImage { get; set; }

    /// <summary>Seconds since the served image was updated, or null if none yet.</summary>
    [JsonPropertyName("image_age_seconds")]
    public int? ImageAgeSeconds { get; set; }

    /// <summary>Whether the served image is older than <see cref="StaleThresholdSeconds"/>.</summary>
    [JsonPropertyName("image_stale")]
    public bool ImageStale { get; set; }

    /// <summary>Age at which the server calls an image stale.</summary>
    [JsonPropertyName("stale_threshold_seconds")]
    public int StaleThresholdSeconds { get; set; }

    /// <summary>Overlay metadata for the latest frame, scrubbed of filesystem paths.</summary>
    [JsonPropertyName("metadata")]
    public Dictionary<string, JsonElement>? Metadata { get; set; }

    /// <summary>Server-local ISO timestamp of the response.</summary>
    [JsonPropertyName("timestamp")]
    public string? Timestamp { get; set; }

    /// <summary>Capture block. Null on an older Sentinel, or if the server failed to derive it.</summary>
    [JsonPropertyName("capture")]
    public SentinelCapture? Capture { get; set; }

    /// <summary>Health block. Null on an older Sentinel, or if the server failed to derive it.</summary>
    [JsonPropertyName("health")]
    public SentinelHealth? Health { get; set; }
}

/// <summary>
/// Outcome of a conditional fetch of <c>GET /latest</c>.
/// </summary>
/// <remarks>
/// Modelled as a result rather than an exception because "no image yet" and
/// "unchanged since last poll" are both entirely normal for a panel polling
/// every few seconds, and neither is a failure.
/// </remarks>
public sealed class SentinelImageResult
{
    private SentinelImageResult()
    {
    }

    /// <summary>
    /// True when the server answered 304 Not Modified: the frame you already
    /// hold is current, and <see cref="Data"/> is null.
    /// </summary>
    public bool Unchanged { get; private init; }

    /// <summary>True when the server has no image yet (HTTP 404).</summary>
    public bool NoImageYet { get; private init; }

    /// <summary>The image bytes, or null for <see cref="Unchanged"/> / <see cref="NoImageYet"/>.</summary>
    public byte[]? Data { get; private init; }

    /// <summary>MIME type of <see cref="Data"/>, e.g. <c>image/jpeg</c>.</summary>
    public string? ContentType { get; private init; }

    /// <summary>
    /// The raw <c>ETag</c> header value, to pass back as
    /// <c>If-None-Match</c> on the next poll.
    /// </summary>
    /// <remarks>
    /// Sentinel emits a bare MD5 hex digest with no quotes, which is not a
    /// syntactically valid entity tag. Treat it as an opaque string and echo it
    /// back byte-for-byte — the server compares it with <c>==</c>, so adding the
    /// quotes a strict client would add breaks 304 handling silently.
    /// </remarks>
    public string? ETag { get; private init; }

    /// <summary>
    /// Value of <c>X-PFR-Image-Age-Seconds</c>, or null when absent.
    /// </summary>
    /// <remarks>
    /// Absent on a 304 — the server sends only <c>ETag</c> there. Keep the age
    /// from the last 200 and add the elapsed wall time, or read
    /// <c>/status</c>, rather than treating null as "fresh".
    /// </remarks>
    public int? AgeSeconds { get; private init; }

    /// <summary>
    /// True when the server sent <c>X-PFR-Image-Stale: true</c>.
    /// </summary>
    /// <remarks>
    /// The signal for greying out the frame instead of presenting an hours-old
    /// image as current. Like <see cref="AgeSeconds"/>, never set on a 304.
    /// </remarks>
    public bool Stale { get; private init; }

    /// <summary>Creates a 200 result.</summary>
    internal static SentinelImageResult FromImage(byte[] data, string? contentType, string? etag, int? age, bool stale) =>
        new()
        {
            Data = data,
            ContentType = contentType,
            ETag = etag,
            AgeSeconds = age,
            Stale = stale,
        };

    /// <summary>Creates a 304 result.</summary>
    internal static SentinelImageResult FromUnchanged(string? etag) =>
        new() { Unchanged = true, ETag = etag };

    /// <summary>Creates a 404 result.</summary>
    internal static SentinelImageResult FromNoImage() =>
        new() { NoImageYet = true };
}

/// <summary>
/// What should happen to an in-flight control command when the caller's
/// <see cref="System.Threading.CancellationToken"/> fires.
/// </summary>
/// <remarks>
/// <para>
/// This choice is exposed rather than decided for you because neither answer is
/// safe in general. Sentinel executes the command <em>before</em> it starts
/// waiting for the target state, so by the time a socket can be aborted the
/// command has already happened. Aborting the request only discards the
/// confirmation.
/// </para>
/// </remarks>
public enum SentinelCancellation
{
    /// <summary>
    /// Abort the request immediately on cancellation and throw
    /// <see cref="SentinelCommandAbandonedException"/>.
    /// </summary>
    /// <remarks>
    /// The right default for a UI button: the operator wants control back now.
    /// Accept that capture may have started anyway, and re-read the state.
    /// </remarks>
    AbandonRequest = 0,

    /// <summary>
    /// Ignore the caller's token once the request is on the wire and return the
    /// server's real answer.
    /// </summary>
    /// <remarks>
    /// The right choice for a sequence item that must know the true final state
    /// before it decides how to unwind — for instance, so it can issue a
    /// compensating Stop only if the Start actually took. The client's own
    /// timeout budget still applies, so this cannot hang forever.
    /// </remarks>
    CompleteRequest = 1,
}

/// <summary>Options for a single Start/Stop call.</summary>
public sealed class SentinelCommandOptions
{
    /// <summary>Server-side wait bounds, from <c>api_control.TIMEOUT_MIN</c>/<c>TIMEOUT_MAX</c>.</summary>
    public const int MinTimeoutSeconds = 1;

    /// <summary>Server-side maximum wait, from <c>api_control.TIMEOUT_MAX</c>.</summary>
    public const int MaxTimeoutSeconds = 300;

    /// <summary>Server-side default wait, from <c>api_control.TIMEOUT_DEFAULT</c>.</summary>
    public const int DefaultTimeoutSeconds = 30;

    /// <summary>
    /// Whether the server should block until capture reaches the target state.
    /// </summary>
    /// <remarks>
    /// True is what makes a sequence step deterministic: the sequence must not
    /// advance while capture is still spinning up. False returns
    /// <see cref="SentinelResults.Pending"/> with the state unconfirmed.
    /// </remarks>
    public bool Wait { get; init; } = true;

    /// <summary>How long the server waits, in seconds. Must be 1..300.</summary>
    public int TimeoutSeconds { get; init; } = DefaultTimeoutSeconds;

    /// <summary>What a caller cancellation does to an in-flight command.</summary>
    public SentinelCancellation CancellationBehaviour { get; init; } = SentinelCancellation.AbandonRequest;

    /// <summary>Validates the options, throwing before anything is sent.</summary>
    /// <remarks>
    /// Checked locally so a bad value is an <see cref="ArgumentOutOfRangeException"/>
    /// at the call site instead of an HTTP 400 with a stack trace pointing at
    /// the socket.
    /// </remarks>
    public void Validate()
    {
        if (TimeoutSeconds is < MinTimeoutSeconds or > MaxTimeoutSeconds)
        {
            throw new ArgumentOutOfRangeException(
                nameof(TimeoutSeconds), TimeoutSeconds,
                $"Sentinel accepts a timeout between {MinTimeoutSeconds} and {MaxTimeoutSeconds} seconds.");
        }
    }
}

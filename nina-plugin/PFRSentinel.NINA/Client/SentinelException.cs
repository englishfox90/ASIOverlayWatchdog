#nullable enable
using System;
using System.Net;
using System.Threading;

namespace PFRSentinel.Nina.Client;

/// <summary>
/// Coarse classification of a Sentinel failure, chosen so a caller can pick
/// operator advice without matching on free text or HTTP status.
/// </summary>
/// <remarks>
/// The values deliberately line up with the exit codes of
/// <c>scripts/nina/Invoke-SentinelCapture.ps1</c> so the two integration paths
/// give an operator the same vocabulary:
/// 2 = <see cref="ConfigNotFound"/>, 3 = <see cref="ControlDisabled"/> /
/// <see cref="ControlUnavailable"/>, 4 = <see cref="Unreachable"/> /
/// <see cref="Protocol"/>, 5 = <see cref="Unauthorized"/> /
/// <see cref="HostNotAllowed"/>, 6 = <see cref="WaitTimedOut"/> /
/// <see cref="ClientTimeout"/>, 7 = <see cref="CommandFailed"/>.
/// </remarks>
public enum SentinelErrorKind
{
    /// <summary>Sentinel's config.json could not be found or read.</summary>
    ConfigNotFound,

    /// <summary>
    /// The control API is switched off in Sentinel (no token configured).
    /// Detected locally from config, or reported by the server as HTTP 503 with
    /// <c>code = "control_disabled"</c>. Fix: enable it on Sentinel's Output tab.
    /// </summary>
    ControlDisabled,

    /// <summary>
    /// Sentinel is running and the token is fine, but no capture command handler
    /// is registered on the web server — HTTP 503 with
    /// <c>code = "control_unavailable"</c>. Fix: restart Sentinel.
    /// </summary>
    /// <remarks>
    /// This is the reason <see cref="SentinelException.Code"/> exists: 503 has
    /// two causes needing *opposite* advice ("turn the feature on" vs "it is on,
    /// restart the app") and the status alone cannot separate them.
    /// </remarks>
    ControlUnavailable,

    /// <summary>Nothing answered on the socket — Sentinel down, or wrong host/port.</summary>
    Unreachable,

    /// <summary>HTTP 401. The token was missing, malformed, or wrong — the server will not say which.</summary>
    Unauthorized,

    /// <summary>HTTP 403. The <c>Host</c> header is not on the control allow-list.</summary>
    HostNotAllowed,

    /// <summary>HTTP 400/413. The request itself was rejected — a client bug.</summary>
    BadRequest,

    /// <summary>
    /// HTTP 504. The server issued the command and then gave up waiting for the
    /// target state. The command <em>was</em> issued; capture may still arrive.
    /// </summary>
    WaitTimedOut,

    /// <summary>
    /// Our own client-side budget expired before the server answered. Distinct
    /// from <see cref="WaitTimedOut"/>: here we do not know what the server did.
    /// </summary>
    ClientTimeout,

    /// <summary>HTTP 500 with a control body — capture reported a real failure.</summary>
    CommandFailed,

    /// <summary>The response was not the shape the contract promises.</summary>
    Protocol,
}

/// <summary>
/// Base type for every Sentinel API failure.
/// </summary>
/// <remarks>
/// <para>
/// Carries the machine-readable <see cref="Code"/> from Sentinel's error bodies
/// (<c>services/web_control.py</c>: <c>bad_request</c>, <c>body_too_large</c>,
/// <c>unauthorized</c>, <c>host_not_allowed</c>, <c>control_disabled</c>,
/// <c>control_unavailable</c>, <c>internal_error</c>). Never branch on
/// <see cref="Message"/> — it is human-facing text and may change.
/// </para>
/// <para>
/// Cancellation is deliberately <em>not</em> modelled here. A user-cancelled
/// command throws <see cref="SentinelCommandAbandonedException"/>, which derives
/// from <see cref="OperationCanceledException"/> instead, so a
/// <c>catch (SentinelException)</c> in a NINA sequence item cannot accidentally
/// swallow a cancellation the sequencer needs to see.
/// </para>
/// </remarks>
public class SentinelException : Exception
{
    /// <summary>Creates a Sentinel failure.</summary>
    public SentinelException(
        SentinelErrorKind kind,
        string message,
        string? code = null,
        HttpStatusCode? statusCode = null,
        Exception? innerException = null)
        : base(message, innerException)
    {
        Kind = kind;
        Code = code;
        StatusCode = statusCode;
    }

    /// <summary>What went wrong, coarsely — the thing to switch on.</summary>
    public SentinelErrorKind Kind { get; }

    /// <summary>
    /// Sentinel's machine-readable <c>code</c> from the error body, when the
    /// response carried one. Null for transport and configuration failures.
    /// </summary>
    public string? Code { get; }

    /// <summary>HTTP status, when the failure came from a response at all.</summary>
    public HttpStatusCode? StatusCode { get; }

    /// <summary>
    /// One line of advice for the observatory operator, phrased as an action.
    /// Safe to render in a NINA sequence log or a validation issue.
    /// </summary>
    public virtual string OperatorAdvice => Kind switch
    {
        SentinelErrorKind.ConfigNotFound =>
            "Sentinel's configuration could not be read. If Sentinel runs on another machine or user account, set an explicit base URL and token in the plugin options.",
        SentinelErrorKind.ControlDisabled =>
            "Enable the capture control API on Sentinel's Output tab, then retry.",
        SentinelErrorKind.ControlUnavailable =>
            "Sentinel is running but capture control is not wired up. Restart Sentinel.",
        SentinelErrorKind.Unreachable =>
            "Sentinel is not reachable. Check it is running with the web server enabled, and that the host and port match.",
        SentinelErrorKind.Unauthorized =>
            "Sentinel rejected the control token. Regenerate it on Sentinel's Output tab.",
        SentinelErrorKind.HostNotAllowed =>
            "Sentinel refused the request's Host header. Control calls are accepted from the same machine only, unless extra hosts are allow-listed in Sentinel's config.",
        SentinelErrorKind.BadRequest =>
            "Sentinel rejected the request as malformed. This is a plugin bug — please report it.",
        SentinelErrorKind.WaitTimedOut =>
            "Capture did not reach the requested state in time. The command WAS issued, so check Sentinel before issuing another.",
        SentinelErrorKind.ClientTimeout =>
            "No reply from Sentinel within the allowed time. The command may or may not have been carried out — check Sentinel's current state before retrying.",
        SentinelErrorKind.CommandFailed =>
            "Capture reported a failure. See the message for the cause, and Sentinel's log for detail.",
        SentinelErrorKind.Protocol =>
            "Sentinel returned an unexpected response. Check that Sentinel and this plugin are both up to date.",
        _ => "See Sentinel's log for detail.",
    };
}

/// <summary>
/// Thrown before any request is sent, when the local configuration cannot yield
/// a usable control credential.
/// </summary>
/// <remarks>
/// Separated from the response-driven failures because the fix is different in
/// kind: nothing about the network is wrong, and retrying will not help until
/// the operator changes a setting.
/// </remarks>
public sealed class SentinelConfigurationException : SentinelException
{
    /// <summary>Creates a configuration failure from a loaded config.</summary>
    public SentinelConfigurationException(SentinelConfig config)
        : base(KindFor(config.Status), config.ProblemDescription)
    {
        ConfigStatus = config.Status;
        ConfigPath = config.ConfigPath;
    }

    /// <summary>The precise local problem.</summary>
    public SentinelConfigStatus ConfigStatus { get; }

    /// <summary>Where we looked for Sentinel's config.json.</summary>
    public string ConfigPath { get; }

    private static SentinelErrorKind KindFor(SentinelConfigStatus status) => status switch
    {
        SentinelConfigStatus.ControlDisabled => SentinelErrorKind.ControlDisabled,
        SentinelConfigStatus.NoToken => SentinelErrorKind.ControlDisabled,
        _ => SentinelErrorKind.ConfigNotFound,
    };
}

/// <summary>Nothing answered on the socket.</summary>
public sealed class SentinelUnreachableException : SentinelException
{
    /// <summary>Creates an unreachable failure for <paramref name="baseUrl"/>.</summary>
    public SentinelUnreachableException(string baseUrl, Exception? innerException = null)
        : base(SentinelErrorKind.Unreachable,
               $"Sentinel is not reachable at {baseUrl}.",
               innerException: innerException)
    {
        BaseUrl = baseUrl;
    }

    /// <summary>The base URL we tried. Never contains the token.</summary>
    public string BaseUrl { get; }
}

/// <summary>
/// Our own client-side deadline expired before Sentinel answered.
/// </summary>
/// <remarks>
/// <para><b>This is not the same as HTTP 504.</b></para>
/// <para>
/// A 504 is the server telling us it issued the command and then gave up
/// waiting — it comes back as a full <see cref="SentinelControlResult"/> with
/// <see cref="SentinelResultKind.Timeout"/>, so we know exactly what happened.
/// This exception means we stopped listening: the command was almost certainly
/// executed, but we have no confirmation either way. Re-read the capture state
/// rather than assuming.
/// </para>
/// </remarks>
public sealed class SentinelTimeoutException : SentinelException
{
    /// <summary>Creates a client-side timeout failure.</summary>
    public SentinelTimeoutException(TimeSpan budget, Exception? innerException = null)
        : base(SentinelErrorKind.ClientTimeout,
               $"Sentinel did not answer within {budget.TotalSeconds:0.#}s.",
               innerException: innerException)
    {
        Budget = budget;
    }

    /// <summary>How long the client was prepared to wait.</summary>
    public TimeSpan Budget { get; }
}

/// <summary>
/// A command was abandoned because the caller cancelled.
/// </summary>
/// <remarks>
/// <para>
/// <b>Cancelling the HTTP request does not un-start capture.</b> By the time a
/// socket can be aborted, Sentinel has already handed the command to the thread
/// that owns capture (<c>services/web_control.py</c> calls the handler
/// <em>before</em> it begins waiting). All that is cancelled is our interest in
/// the answer.
/// </para>
/// <para>
/// <see cref="CommandMayHaveTakenEffect"/> is always <c>true</c> for this
/// reason. A caller that must guarantee capture is stopped after a cancelled
/// sequence has to issue an explicit <see cref="SentinelClient.StopAsync"/> with
/// a fresh, uncancelled token — the client will not do that behind your back,
/// because "stop what I started" and "leave it running, I only stopped
/// watching" are both legitimate and only the caller knows which it wants.
/// </para>
/// <para>
/// Derives from <see cref="OperationCanceledException"/> (not
/// <see cref="SentinelException"/>) so NINA's sequencer sees a normal
/// cancellation and a <c>catch (SentinelException)</c> cannot swallow it.
/// </para>
/// </remarks>
public sealed class SentinelCommandAbandonedException : OperationCanceledException
{
    // VERIFY (Stage 1a spike, with NINA.Sequencer.dll to hand): that NINA's
    // sequencer treats an OperationCanceledException as a clean cancellation
    // rather than a failed step. If it does not, this should carry a different
    // base type — but it must still not derive from SentinelException.

    /// <summary>Creates an abandoned-command cancellation.</summary>
    /// <param name="command">The command that had already been sent, e.g. <c>start</c>.</param>
    /// <param name="token">The token that requested cancellation.</param>
    public SentinelCommandAbandonedException(string command, CancellationToken token)
        : base($"The '{command}' request was cancelled. The command may already have been carried out by Sentinel.", token)
    {
        Command = command;
    }

    /// <summary>The command that was in flight: <c>start</c> or <c>stop</c>.</summary>
    public string Command { get; }

    /// <summary>
    /// Always <c>true</c>. Kept as a property so the call site reads as an
    /// explicit acknowledgement rather than tribal knowledge.
    /// </summary>
    public bool CommandMayHaveTakenEffect => true;
}

/// <summary>HTTP 401 — the token was missing, malformed, or wrong.</summary>
/// <remarks>
/// Thrown only after the config has been re-read and retried once, so by the
/// time a caller sees this the token really is wrong rather than merely stale.
/// </remarks>
public sealed class SentinelUnauthorizedException : SentinelException
{
    /// <summary>Creates a 401 failure.</summary>
    public SentinelUnauthorizedException(string? code)
        : base(SentinelErrorKind.Unauthorized,
               "Sentinel rejected the control token.",
               code, HttpStatusCode.Unauthorized)
    {
    }
}

/// <summary>HTTP 403 — the request's <c>Host</c> header is not allow-listed.</summary>
public sealed class SentinelForbiddenException : SentinelException
{
    /// <summary>Creates a 403 failure.</summary>
    public SentinelForbiddenException(string? message, string? code)
        : base(SentinelErrorKind.HostNotAllowed,
               message ?? "Sentinel rejected the request's Host header.",
               code, HttpStatusCode.Forbidden)
    {
    }
}

/// <summary>
/// HTTP 503 — control is unavailable, for one of two very different reasons.
/// </summary>
/// <remarks>
/// <see cref="ControlDisabled"/> means the operator has not turned the feature
/// on; <see cref="ControlUnwired"/> means they have, but Sentinel started
/// without registering a capture handler and needs restarting. Only
/// <see cref="SentinelException.Code"/> separates them — never the status, and
/// never the message text.
/// </remarks>
public sealed class SentinelUnavailableException : SentinelException
{
    /// <summary>Sentinel's <c>code</c> for "no token configured".</summary>
    public const string CodeControlDisabled = "control_disabled";

    /// <summary>Sentinel's <c>code</c> for "no capture handler registered".</summary>
    public const string CodeControlUnavailable = "control_unavailable";

    /// <summary>Creates a 503 failure from the body's code.</summary>
    public SentinelUnavailableException(string? message, string? code)
        : base(code == CodeControlUnavailable ? SentinelErrorKind.ControlUnavailable : SentinelErrorKind.ControlDisabled,
               message ?? "Capture control is not available on this Sentinel server.",
               code, HttpStatusCode.ServiceUnavailable)
    {
    }

    /// <summary>The control API is switched off. Fix: enable it on the Output tab.</summary>
    public bool ControlDisabled => Kind == SentinelErrorKind.ControlDisabled;

    /// <summary>Control is on but not wired up. Fix: restart Sentinel.</summary>
    public bool ControlUnwired => Kind == SentinelErrorKind.ControlUnavailable;
}

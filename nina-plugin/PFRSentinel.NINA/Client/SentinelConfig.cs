#nullable enable
using System;
using System.Globalization;
using System.IO;
using System.Text.Json;

namespace PFRSentinel.Nina.Client;

/// <summary>
/// Why a discovered configuration is or is not usable for capture control.
/// </summary>
/// <remarks>
/// These are kept apart because each needs different operator advice, and
/// because collapsing them into "not configured" is exactly the failure mode
/// that makes an integration frustrating to set up.
/// </remarks>
public enum SentinelConfigStatus
{
    /// <summary>A base URL and a control token are both available.</summary>
    Ok,

    /// <summary>config.json was not at the expected path — Sentinel may never have run, or runs elsewhere.</summary>
    ConfigNotFound,

    /// <summary>config.json exists but could not be read or parsed (locked mid-write, corrupt, wrong file).</summary>
    ConfigUnreadable,

    /// <summary><c>output.webserver_control_enabled</c> is false. Sentinel mints no token until control is enabled.</summary>
    ControlDisabled,

    /// <summary>Control is enabled but <c>output.api_token</c> is empty — Sentinel has not minted one yet.</summary>
    NoToken,
}

/// <summary>
/// Explicit values that win over anything discovered in Sentinel's config.json.
/// </summary>
/// <remarks>
/// Exists for the one case config discovery cannot cover: Sentinel and NINA on
/// different machines or different Windows accounts, where reading
/// <c>%LOCALAPPDATA%</c> finds someone else's (or no) install.
/// </remarks>
public sealed class SentinelConfigOverrides
{
    /// <summary>Full base URL, e.g. <c>http://127.0.0.1:8080</c>. Null to derive from config.</summary>
    public string? BaseUrl { get; init; }

    /// <summary>
    /// Bearer token. Null to read from config.
    /// </summary>
    /// <remarks>
    /// Supplying this also suppresses the local <see cref="SentinelConfigStatus.ControlDisabled"/>
    /// check: if you have hand-carried a token from another machine, we cannot
    /// see that machine's enabled flag, so we let the server be the judge — it
    /// answers 503 <c>control_disabled</c> if control really is off.
    /// It also disables the 401 re-read-and-retry path, since an override is by
    /// definition not something a config reload can refresh.
    /// </remarks>
    public string? Token { get; init; }

    /// <summary>Alternative path to Sentinel's config.json.</summary>
    public string? ConfigPath { get; init; }

    /// <summary>Base path of the control routes. Null to read <c>output.webserver_control_path</c>.</summary>
    public string? ControlPath { get; init; }

    /// <summary>Path of the status endpoint. Null to read <c>output.webserver_status_path</c>.</summary>
    public string? StatusPath { get; init; }

    /// <summary>Path of the latest-image endpoint. Null to read <c>output.webserver_path</c>.</summary>
    public string? ImagePath { get; init; }
}

/// <summary>
/// An immutable snapshot of where Sentinel is and how to talk to it, discovered
/// from <c>%LOCALAPPDATA%\PFRSentinel\config.json</c>.
/// </summary>
/// <remarks>
/// <para>
/// Mirrors <c>scripts/nina/Invoke-SentinelCapture.ps1</c>, which is the
/// reference implementation of this discovery. Reading Sentinel's own config is
/// what makes the integration zero-configuration: there is no token to paste
/// into NINA.
/// </para>
/// <para>
/// <b>LOCALAPPDATA, not APPDATA.</b> Sentinel's user-facing docs mention
/// <c>%APPDATA%</c>, but <c>app_config.get_config_dir()</c> resolves to
/// <c>%LOCALAPPDATA%\PFRSentinel</c>. Reading the roaming path finds nothing.
/// </para>
/// <para>
/// A snapshot is deliberately immutable and cheap to re-take: the token can be
/// regenerated in Sentinel's UI while NINA is running, so anything holding a
/// config for more than one request must go through
/// <see cref="SentinelConfigProvider"/>.
/// </para>
/// </remarks>
public sealed class SentinelConfig
{
    /// <summary>Sentinel's default web-server port (<c>output.webserver_port</c>).</summary>
    public const int DefaultPort = 8080;

    /// <summary>Sentinel's default bind host (<c>output.webserver_host</c>).</summary>
    public const string DefaultHost = "127.0.0.1";

    /// <summary>Sentinel's default control base path (<c>output.webserver_control_path</c>).</summary>
    public const string DefaultControlPath = "/capture";

    /// <summary>Sentinel's default status path (<c>output.webserver_status_path</c>).</summary>
    public const string DefaultStatusPath = "/status";

    /// <summary>Sentinel's default image path (<c>output.webserver_path</c>).</summary>
    public const string DefaultImagePath = "/latest";

    // Bind addresses that name no reachable host. Mirrors _WILDCARD_BINDS in
    // services/api_auth.py — a wildcard is an address to listen on, never one to
    // connect to, and http://0.0.0.0:8080 simply does not resolve.
    private static readonly string[] WildcardBinds = { "0.0.0.0", "::", "[::]", "" };

    private SentinelConfig(
        string baseUrl,
        string controlPath,
        string statusPath,
        string imagePath,
        string token,
        bool controlEnabled,
        SentinelConfigStatus status,
        string configPath,
        bool tokenFromOverride,
        string? readDetail)
    {
        BaseUrl = baseUrl;
        ControlPath = controlPath;
        StatusPath = statusPath;
        ImagePath = imagePath;
        Token = token;
        ControlEnabled = controlEnabled;
        Status = status;
        ConfigPath = configPath;
        TokenFromOverride = tokenFromOverride;
        ReadDetail = readDetail;
    }

    /// <summary>Base URL with no trailing slash, e.g. <c>http://127.0.0.1:8080</c>.</summary>
    public string BaseUrl { get; }

    /// <summary>Control base path with a leading and no trailing slash, e.g. <c>/capture</c>.</summary>
    public string ControlPath { get; }

    /// <summary>Status endpoint path, e.g. <c>/status</c>.</summary>
    public string StatusPath { get; }

    /// <summary>Latest-image endpoint path, e.g. <c>/latest</c>.</summary>
    public string ImagePath { get; }

    /// <summary>
    /// The bearer token, or an empty string.
    /// </summary>
    /// <remarks>
    /// <b>Never log, print, serialise, or put this in an exception message.</b>
    /// <see cref="ToString"/> is overridden to keep it out of accidental
    /// interpolation, but that only helps where <c>ToString</c> is what runs.
    /// </remarks>
    public string Token { get; }

    /// <summary>Whether <c>output.webserver_control_enabled</c> was true.</summary>
    public bool ControlEnabled { get; }

    /// <summary>Whether this configuration can be used to issue control commands.</summary>
    public SentinelConfigStatus Status { get; }

    /// <summary>The config.json path this snapshot was taken from (whether or not it existed).</summary>
    public string ConfigPath { get; }

    /// <summary>Whether the token came from an override rather than from config.json.</summary>
    public bool TokenFromOverride { get; }

    /// <summary>Extra detail about a read failure (exception message), for logging. Never contains the token.</summary>
    public string? ReadDetail { get; }

    /// <summary>Whether a non-empty token is available.</summary>
    public bool HasToken => Token.Length > 0;

    /// <summary>Whether control commands can be attempted.</summary>
    public bool IsControlUsable => Status == SentinelConfigStatus.Ok;

    /// <summary>Absolute URI of <c>POST &lt;control&gt;/start</c>.</summary>
    public Uri StartUri => new(BaseUrl + ControlPath + "/start");

    /// <summary>Absolute URI of <c>POST &lt;control&gt;/stop</c>.</summary>
    public Uri StopUri => new(BaseUrl + ControlPath + "/stop");

    /// <summary>Absolute URI of <c>GET &lt;control&gt;</c> (the capture-state alias).</summary>
    public Uri CaptureStateUri => new(BaseUrl + ControlPath);

    /// <summary>Absolute URI of <c>GET /status</c>.</summary>
    public Uri StatusUri => new(BaseUrl + StatusPath);

    /// <summary>Absolute URI of <c>GET /latest</c>.</summary>
    public Uri ImageUri => new(BaseUrl + ImagePath);

    /// <summary>The default location of Sentinel's config.json.</summary>
    public static string DefaultConfigPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "PFRSentinel",
        "config.json");

    /// <summary>A one-line, operator-facing description of why control is unusable.</summary>
    public string ProblemDescription => Status switch
    {
        SentinelConfigStatus.Ok =>
            "Sentinel control API configured.",
        SentinelConfigStatus.ConfigNotFound =>
            $"Sentinel configuration not found at {ConfigPath}. Set an explicit base URL and token if Sentinel runs elsewhere.",
        SentinelConfigStatus.ConfigUnreadable =>
            $"Sentinel configuration at {ConfigPath} could not be read.",
        SentinelConfigStatus.ControlDisabled =>
            "The capture control API is switched off in Sentinel. Enable it on the Output tab, then retry.",
        SentinelConfigStatus.NoToken =>
            "No control API token is configured in Sentinel. Enable the control API on the Output tab to mint one.",
        _ => "Sentinel control API is unavailable.",
    };

    /// <summary>Reads Sentinel's config.json and resolves a usable endpoint set.</summary>
    /// <param name="overrides">Explicit values that win over the file. May be null.</param>
    /// <remarks>
    /// Never throws for a missing, locked, or corrupt file — the outcome is
    /// reported through <see cref="Status"/>. A caller polling every few seconds
    /// must not have to guard every read with a try/catch.
    /// </remarks>
    public static SentinelConfig Load(SentinelConfigOverrides? overrides = null)
    {
        overrides ??= new SentinelConfigOverrides();
        string configPath = overrides.ConfigPath ?? DefaultConfigPath;

        JsonElement? output = null;
        SentinelConfigStatus? readFailure = null;
        string? readDetail = null;

        try
        {
            if (!File.Exists(configPath))
            {
                readFailure = SentinelConfigStatus.ConfigNotFound;
            }
            else
            {
                // ReadAllText strips a UTF-8 BOM; JsonDocument.Parse would choke
                // on one. Sentinel writes without a BOM today, but a user who has
                // hand-edited the file in Notepad may not have.
                string raw = File.ReadAllText(configPath);
                using JsonDocument document = JsonDocument.Parse(raw);
                if (document.RootElement.ValueKind == JsonValueKind.Object &&
                    document.RootElement.TryGetProperty("output", out JsonElement outputElement) &&
                    outputElement.ValueKind == JsonValueKind.Object)
                {
                    // JsonDocument owns pooled buffers freed on Dispose, so the
                    // element cannot outlive the using block — clone it out.
                    output = outputElement.Clone();
                }
                else
                {
                    readFailure = SentinelConfigStatus.ConfigUnreadable;
                    readDetail = "config.json has no 'output' section — is this a current Sentinel install?";
                }
            }
        }
        catch (Exception ex)
        {
            // Deliberately broad. This method promises never to throw, and the
            // set of things that can go wrong reading a user-editable file on an
            // arbitrary Windows install (locked mid-write, ACLs, a path on a
            // disconnected drive, invalid JSON) is not worth enumerating.
            readFailure = SentinelConfigStatus.ConfigUnreadable;
            readDetail = ex.Message;
        }

        string token = overrides.Token ?? ReadString(output, "api_token", string.Empty);
        bool tokenFromOverride = overrides.Token is not null;

        // With an explicit token we cannot see (and should not second-guess) the
        // remote install's enabled flag; let the server answer 503 instead.
        bool controlEnabled = tokenFromOverride || ReadBool(output, "webserver_control_enabled", false);

        string baseUrl = overrides.BaseUrl is { Length: > 0 }
            ? overrides.BaseUrl.TrimEnd('/')
            : BuildBaseUrl(output);

        string controlPath = NormalisePath(overrides.ControlPath ?? ReadString(output, "webserver_control_path", DefaultControlPath), DefaultControlPath);
        string statusPath = NormalisePath(overrides.StatusPath ?? ReadString(output, "webserver_status_path", DefaultStatusPath), DefaultStatusPath);
        string imagePath = NormalisePath(overrides.ImagePath ?? ReadString(output, "webserver_path", DefaultImagePath), DefaultImagePath);

        SentinelConfigStatus status;
        if (token.Length > 0)
        {
            status = SentinelConfigStatus.Ok;
        }
        else if (readFailure is not null)
        {
            // No token AND no readable config: the file problem is the root
            // cause, and reporting "control disabled" here would send the
            // operator to a settings tab that may not even exist on this machine.
            status = readFailure.Value;
        }
        else if (!controlEnabled)
        {
            status = SentinelConfigStatus.ControlDisabled;
        }
        else
        {
            status = SentinelConfigStatus.NoToken;
        }

        return new SentinelConfig(
            baseUrl, controlPath, statusPath, imagePath, token,
            controlEnabled, status, configPath, tokenFromOverride, readDetail);
    }

    private static string BuildBaseUrl(JsonElement? output)
    {
        string host = ReadString(output, "webserver_host", DefaultHost);
        if (Array.IndexOf(WildcardBinds, host) >= 0)
        {
            // A wildcard bind names no reachable host. Loopback is not just a
            // fallback here, it is the correct target: the control routes'
            // Host allow-list always accepts loopback, and any other name would
            // need explicitly allow-listing in Sentinel.
            host = DefaultHost;
        }

        int port = ReadInt(output, "webserver_port", DefaultPort);
        if (port is <= 0 or > 65535)
        {
            port = DefaultPort;
        }

        // Bracket a bare IPv6 literal so the authority parses. A ':' with no
        // '[' can only be IPv6 here — a host:port pair is not what this key holds.
        if (host.Contains(':') && !host.StartsWith('['))
        {
            host = "[" + host + "]";
        }

        return "http://" + host + ":" + port.ToString(CultureInfo.InvariantCulture);
    }

    private static string NormalisePath(string value, string fallback)
    {
        string path = (value ?? string.Empty).Trim();
        if (path.Length == 0)
        {
            path = fallback;
        }

        if (!path.StartsWith('/'))
        {
            path = "/" + path;
        }

        // The server compares against a path with the trailing slash stripped
        // (web_control.route_post), so strip it here too and never emit "//start".
        path = path.TrimEnd('/');
        return path.Length == 0 ? fallback : path;
    }

    private static string ReadString(JsonElement? output, string name, string fallback)
    {
        if (output is null || !output.Value.TryGetProperty(name, out JsonElement value))
        {
            return fallback;
        }

        return value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? fallback
            : fallback;
    }

    private static bool ReadBool(JsonElement? output, string name, bool fallback)
    {
        if (output is null || !output.Value.TryGetProperty(name, out JsonElement value))
        {
            return fallback;
        }

        return value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => fallback,
        };
    }

    private static int ReadInt(JsonElement? output, string name, int fallback)
    {
        if (output is null || !output.Value.TryGetProperty(name, out JsonElement value))
        {
            return fallback;
        }

        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out int number))
        {
            return number;
        }

        // A hand-edited config can hold "8080" as a string.
        if (value.ValueKind == JsonValueKind.String &&
            int.TryParse(value.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out int parsed))
        {
            return parsed;
        }

        return fallback;
    }

    /// <summary>A description that deliberately omits the token.</summary>
    public override string ToString() =>
        $"SentinelConfig(BaseUrl={BaseUrl}, ControlPath={ControlPath}, Status={Status}, HasToken={HasToken})";
}

/// <summary>
/// Holds the current <see cref="SentinelConfig"/> and re-reads it on demand.
/// </summary>
/// <remarks>
/// <para>
/// The token can be regenerated in Sentinel's UI at any moment, including while
/// a NINA session is running. A client that caches a token for the lifetime of
/// the process starts failing with 401 and no obvious cause, so the refresh path
/// has to exist and has to be cheap.
/// </para>
/// <para>Thread-safe: reads are lock-free, reloads are serialised.</para>
/// </remarks>
public sealed class SentinelConfigProvider
{
    private readonly object _gate = new();
    private readonly SentinelConfigOverrides _overrides;
    private volatile SentinelConfig? _current;

    /// <summary>Creates a provider, optionally with explicit overrides.</summary>
    public SentinelConfigProvider(SentinelConfigOverrides? overrides = null)
    {
        _overrides = overrides ?? new SentinelConfigOverrides();
    }

    /// <summary>
    /// Whether the token is pinned by an override, so reloading can never change it.
    /// </summary>
    /// <remarks>
    /// The 401 retry path checks this: re-reading a file that is not the source
    /// of the credential just wastes a request and muddies the error.
    /// </remarks>
    public bool HasTokenOverride => _overrides.Token is not null;

    /// <summary>The cached configuration, loading it on first access.</summary>
    public SentinelConfig Current => _current ?? Reload();

    /// <summary>Re-reads config.json and replaces the cached snapshot.</summary>
    /// <returns>The freshly loaded configuration.</returns>
    public SentinelConfig Reload()
    {
        lock (_gate)
        {
            SentinelConfig loaded = SentinelConfig.Load(_overrides);
            _current = loaded;
            return loaded;
        }
    }
}

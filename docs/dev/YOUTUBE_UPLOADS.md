# YouTube Timelapse Uploads

This guide explains how to let PFR Sentinel upload completed timelapse videos
to YouTube. The feature is Windows-only because PFR Sentinel itself is
Windows-only.

## Before You Start

Use a dedicated Google/YouTube account for observatory uploads. Do not use your
primary Google account or an account that contains important personal data. This
does not bypass YouTube rules; it only limits damage if YouTube, Google Cloud,
or OAuth flags the upload account.

Start with YouTube privacy set to `Private`. Confirm that uploads work before
trying `Unlisted` or `Public`.

You need:

- A Google account with a YouTube channel created.
- Access to Google Cloud Console.
- PFR Sentinel running on the Windows machine that records timelapses.
- A completed `.mp4` timelapse to test with.

## Step 1: Create The Google Cloud Project

1. Open https://console.cloud.google.com/.
2. Click the project selector at the top of the page.
3. Click `New Project`.
4. Name it something clear, for example `PFR Sentinel YouTube Uploads`.
5. Click `Create`.
6. Make sure the new project is selected before continuing.

## Step 2: Enable The YouTube Data API

1. In Google Cloud Console, open `APIs & Services`.
2. Open `Library`.
3. Search for `YouTube Data API v3`.
4. Click it.
5. Click `Enable`.

PFR Sentinel uses the YouTube Data API `videos.insert` upload endpoint.

## Step 3: Configure The OAuth Consent Screen

1. In Google Cloud Console, open `APIs & Services`.
2. Open `OAuth consent screen` or `Google Auth Platform`.
3. For most users, choose `External`.
4. Fill in the app name, support email, and developer contact email.
5. Add the scope:

   ```text
   https://www.googleapis.com/auth/youtube.upload
   ```

6. If the app is in `Testing`, add the Google account that will upload videos
   as a test user.

Important OAuth behavior:

- `Testing` mode is easiest for a first upload, but Google says test-user
  authorizations expire seven days after consent when non-basic scopes are used.
  That means unattended uploads can start failing with `auth_expired` until you
  authenticate again in PFR Sentinel.
- `In production` mode avoids the 7-day testing-token behavior, but sensitive
  scopes can require Google verification before the app looks fully trusted.
- Unverified apps can show warning screens, may hit user caps, and may force or
  effectively limit uploads to `Private` depending on account/app status.

Reference: https://support.google.com/cloud/answer/15549945

## Step 4: Create A Desktop OAuth Client

1. In Google Cloud Console, open `APIs & Services` then `Credentials`.
2. Click `Create Credentials`.
3. Choose `OAuth client ID`.
4. Choose application type `Desktop app`.
5. Name it `PFR Sentinel Desktop`.
6. Click `Create`.
7. Click `Download JSON`.
8. Save the JSON somewhere you will not delete. Treat it like a secret.

Do not paste this JSON into Discord, GitHub issues, screenshots, or logs.

## Step 5: Connect PFR Sentinel

1. Open PFR Sentinel.
2. Open the `Timelapse` page.
3. Scroll to the `YouTube Uploads` section and click its header to expand it.
4. Turn on `Enable YouTube uploads`.
5. Click `Browse` next to `OAuth JSON`.
6. Select the downloaded desktop-client JSON file.
7. Leave privacy set to `Private` for the first test.
8. Click `Authenticate`.
9. A browser window opens. Sign in with the dedicated upload account.
10. Accept the YouTube upload permission.
11. Return to PFR Sentinel and confirm the card says authentication completed.

Authentication is only started when you click `Authenticate`. Automatic
timelapse completion will never open a browser or ask for Google approval.

## Step 6: Test A Private Upload

1. Make sure at least one completed timelapse `.mp4` exists.
2. In the `YouTube Uploads` section, click `Upload latest video`.
3. Wait for the status text to show the upload result. On success it shows a
   clickable link to the uploaded video.
4. Open YouTube Studio for the upload account.
5. Confirm the video exists and is `Private`.

After that works, decide whether `Unlisted` or `Public` is appropriate for the
account. If Google or YouTube keeps forcing uploads to `Private`, publish and
verify the OAuth app before assuming PFR Sentinel is broken.

## What Gets Stored

PFR Sentinel stores YouTube runtime files under:

```text
%LOCALAPPDATA%\PFRSentinel
```

Files:

- `youtube_token.json`: OAuth token for the dedicated upload account.
- `youtube_upload_state.json`: upload status and resumable-session state.

Tokens are not stored in `config.json`. Token and state files are written with
a temp file and `os.replace` so power loss is less likely to corrupt them.

## Troubleshooting

Authentication and upload failures are written to the log with a sanitized
reason. Check the in-app `Logs` page, or
`%APPDATA%\PFRSentinel\logs\watchdog.log`, for a line such as
`YouTube upload failed [status]: ...` or
`YouTube authentication failed [status]: ...`.

`OAuth client JSON was not found.`
: Select the downloaded desktop-client JSON again. Do not select a service
  account JSON; YouTube uploads need user OAuth.

`Authenticate YouTube before uploading.`
: Click `Authenticate` in the YouTube card and approve access in the browser.

`YouTube authorization expired.`
: Click `Authenticate` again. This is expected every seven days when the Google
  Cloud project is still in `Testing` mode.

`YouTube rejected the upload. Check authorization, quota, and channel permissions.`
: Check that the signed-in account owns or manages the YouTube channel, that the
  channel can upload videos, and that the Cloud project still has quota.

`YouTube Data API v3 has not been used in project ... or it is disabled.`
: The YouTube Data API is not enabled on the Cloud project tied to your OAuth
  client. Complete Step 2 (enable `YouTube Data API v3`) for that exact project,
  wait a few minutes for it to propagate, then retry. This surfaces as an
  `accessNotConfigured` 403 and is logged under the `quota_or_permission` status.

`No completed timelapse video was found.`
: Record and finalize a timelapse first. PFR Sentinel ignores the active
  recording file so it does not upload a file that ffmpeg is still writing.

Uploads stop after working for a week.
: Move the OAuth app from `Testing` to `In production` and complete any Google
  verification steps, or plan to re-authenticate weekly.

## Quota Notes

YouTube quota is project-based. Google documents a default allocation of 10,000
units per day, and every request costs at least one quota unit even if it fails.
Upload calls are quota-sensitive, so PFR Sentinel uses resumable uploads,
stores the resumable session URI, and keeps retry counts bounded.

References:

- https://developers.google.com/youtube/v3/determine_quota_cost
- https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits

## Developer Notes

Implementation invariants:

- Keep the `youtube` config block flat. `Config.load()` does a shallow nested
  update, so nested config dicts can clobber future defaults.
- Do not start OAuth from background completion paths. Uploads can enqueue only
  if a token already exists.
- Catch Google/OAuth exceptions at the module boundary and convert them to
  sanitized typed results before logging, analytics, or UI display.
- Log auth and upload failures via `app_logger` with the sanitized status and
  detail (`YouTube ... failed [status]: ...`) so setup problems are diagnosable
  from the logs without leaking secrets.
- Keep token/state files separate from `config.json`.
- Use `services.utils_paths.get_app_data_dir()` for runtime paths.
- Prefer resumable continuation over a new insert after interruption.
- Keep the upload queue bounded and tracked. YouTube uploads are long-running,
  quota-sensitive, and dedup-sensitive.
- The YouTube UI is a `CollapsibleCard` section on the Timelapse page and renders
  the completed-video watch URL as a clickable link (`setOpenExternalLinks`).

Packaging requirements:

- `google-api-python-client`
- `google-auth-oauthlib`
- `google-auth-httplib2`
- `httplib2`
- `oauthlib`
- `requests-oauthlib`
- `uritemplate`
- `googleapiclient/discovery_cache/documents/`

Source-mode tests are not enough. The installed Windows `.exe` must authenticate
and perform a Private test upload to catch frozen-import issues.

Analytics must not include tokens, auth codes, client secrets, full paths,
upload URLs, titles, descriptions, tags, channel IDs, video IDs, or watch URLs.

## Future: YouTube Live Streaming

Uploading a finished MP4 is not the same as streaming live video. Live streaming
should be a separate feature and should use YouTube's Live Streaming API plus a
local encoder process such as ffmpeg.

Required API shape:

1. Add a separate OAuth scope such as:

   ```text
   https://www.googleapis.com/auth/youtube.force-ssl
   ```

   The current `youtube.upload` scope is for video uploads and is not enough for
   creating live broadcasts and streams.

2. Create or reuse a `liveStream` with `liveStreams.insert`. The stream defines
   ingestion settings such as frame rate, ingestion type, and resolution.

3. Create a `liveBroadcast` with `liveBroadcasts.insert`. The broadcast defines
   title, scheduled start time, privacy, made-for-kids setting, and live
   behavior such as auto-start/auto-stop.

4. Bind the broadcast to the stream with `liveBroadcasts.bind`.

5. Start ffmpeg locally and push frames/video to the YouTube RTMP ingestion URL
   from the `liveStream` resource. This is separate from the Data API request.

6. Poll stream/broadcast status. Only transition to `testing` or `live` after
   YouTube reports the bound stream is active.

7. Stop the encoder and transition the broadcast to `complete` when streaming
   ends.

Live-streaming user setup must also explain that the YouTube channel needs live
streaming enabled and YouTube can block or delay live-stream access at the
account/channel level.

References:

- https://developers.google.com/youtube/v3/live/docs/liveStreams/insert
- https://developers.google.com/youtube/v3/live/docs/liveBroadcasts/insert
- https://developers.google.com/youtube/v3/live/docs/liveBroadcasts/bind
- https://developers.google.com/youtube/v3/live/docs/liveBroadcasts/transition

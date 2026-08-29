#nullable enable
using System;
using System.IO;
using System.Windows.Media.Imaging;

namespace PFRSentinel.NINA.SentinelDockables {

    /// <summary>
    /// Turns the bytes of <c>GET /latest</c> into a frozen <see cref="BitmapSource"/>.
    /// </summary>
    /// <remarks>
    /// Decoding happens on the poll thread, not the UI thread, so the result must be
    /// frozen before it crosses over — an unfrozen <see cref="BitmapSource"/> belongs to
    /// the thread that made it and throws on first use anywhere else.
    /// <para>
    /// <see cref="BitmapCacheOption.OnLoad"/> is what makes that possible: it decodes
    /// eagerly, so the frame does not keep a reference to the stream and the bitmap can
    /// be frozen straight away.
    /// </para>
    /// </remarks>
    internal static class SentinelImageDecoder {

        /// <summary>Decodes image bytes, returning null and a reason on failure.</summary>
        /// <param name="data">Bytes from <c>/latest</c>.</param>
        /// <param name="error">Set to an operator-facing reason when decoding fails.</param>
        public static BitmapSource? TryDecode(byte[] data, out string? error) {
            error = null;

            if (data.Length == 0) {
                error = "Sentinel returned an empty image.";
                return null;
            }

            try {
                using var stream = new MemoryStream(data, writable: false);

                var bitmap = new BitmapImage();
                bitmap.BeginInit();
                bitmap.CacheOption = BitmapCacheOption.OnLoad;
                bitmap.CreateOptions = BitmapCreateOptions.PreservePixelFormat;
                bitmap.StreamSource = stream;
                bitmap.EndInit();

                if (bitmap.CanFreeze) {
                    bitmap.Freeze();
                    return bitmap;
                }

                // Not expected with OnLoad, but a bitmap that cannot be frozen would
                // fault the UI thread rather than this one, which is much harder to
                // trace. Copy it into something that can be.
                var copy = new WriteableBitmap(bitmap);
                copy.Freeze();
                return copy;
            } catch (Exception ex) {
                error = $"The latest frame could not be decoded ({ex.GetType().Name}).";
                return null;
            }
        }
    }
}

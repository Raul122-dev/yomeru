import { useEffect, useState, type ImgHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

/** Widths the server can produce (core/images.py WIDTHS). */
const WIDTHS = [160, 320, 640, 1024, 1600, 2400];
const MAX_RETRIES = 2;

/** Append ?w= (or &w=) to an image endpoint URL. */
function sized(url: string, w: number) {
  return `${url}${url.includes("?") ? "&" : "?"}w=${w}`;
}

interface ImgProps extends Omit<ImgHTMLAttributes<HTMLImageElement>, "src" | "srcSet"> {
  /** Any yomeru image endpoint (it accepts ?w=). */
  src: string;
  /** Rendered CSS width hint for the browser, e.g. "50vw" or "160px". */
  sizes?: string;
  /** Largest width worth requesting for this slot. */
  maxWidth?: number;
  /** Keep the page's natural aspect while loading (avoids layout jumps). */
  aspect?: string;
  imgClassName?: string;
}

/**
 * Progressive image: a ~1 KB 32px blur shows instantly, then the browser picks
 * the right WebP from srcset (screen width × DPR) and it fades in.
 * Full-resolution originals are only fetched by editors / "open original".
 */
export function Img({ src, sizes = "100vw", maxWidth = 2400, aspect, className, imgClassName, alt = "", ...rest }: ImgProps) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => { setLoaded(false); setFailed(false); setAttempt(0); }, [src]);

  // A transient error (server busy, connection reset) shouldn't leave a blank
  // slot until a manual reload: retry twice with backoff, then give up.
  const onError = () => {
    if (attempt >= MAX_RETRIES) return setFailed(true);
    setTimeout(() => setAttempt((a) => a + 1), 800 * 2 ** attempt);
  };
  const url = attempt ? `${src}${src.includes("?") ? "&" : "?"}retry=${attempt}` : src;
  const widths = WIDTHS.filter((w) => w <= maxWidth);
  const srcSet = widths.map((w) => `${sized(url, w)} ${w}w`).join(", ");

  return (
    <div className={cn("relative overflow-hidden bg-[hsl(var(--bg-subtle))]", className)} style={aspect ? { aspectRatio: aspect } : undefined}>
      {!loaded && !failed && (
        <img src={sized(src, 32)} alt="" aria-hidden
             className={cn("absolute inset-0 size-full scale-110 object-cover blur-xl", imgClassName)} />
      )}
      {failed ? (
        <div className="grid size-full min-h-24 place-items-center text-xs text-[hsl(var(--text-muted))]">Image unavailable</div>
      ) : (
        <img
          {...rest}
          alt={alt}
          key={attempt}
          src={sized(url, widths[widths.length - 1])}
          srcSet={srcSet}
          sizes={sizes}
          decoding="async"
          onLoad={() => setLoaded(true)}
          onError={onError}
          className={cn("relative block size-full transition-opacity duration-300", loaded ? "opacity-100" : "opacity-0", imgClassName)}
        />
      )}
    </div>
  );
}

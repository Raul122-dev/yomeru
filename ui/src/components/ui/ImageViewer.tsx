/**
 * ImageViewer — optimized image with a lightbox.
 * The inline image and the lightbox use resized WebP variants (see Img);
 * "original" opens the untouched full-resolution file.
 */
import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { ExternalLink, X, ZoomIn } from "lucide-react";
import { cn } from "../../lib/utils";
import { Img } from "./Img";

interface ImageViewerProps {
  src: string;
  alt?: string;
  className?: string;
  label?: string;
  /** CSS width of the inline slot, for srcset selection. Default: half the screen. */
  sizes?: string;
}

export function ImageViewer({ src, alt, className, label, sizes = "(min-width: 1024px) 45vw, 95vw" }: ImageViewerProps) {
  const [open, setOpen] = useState(false);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          className={cn(
            "group relative block w-full cursor-zoom-in overflow-hidden rounded-[var(--radius-sm)] border border-[hsl(var(--border))]",
            className,
          )}
        >
          <Img src={src} alt={alt} sizes={sizes} maxWidth={1600} loading="lazy" imgClassName="h-auto object-contain" className="min-h-40" />
          <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition-all group-hover:bg-black/20">
            <ZoomIn size={18} className="text-white opacity-0 drop-shadow transition-opacity group-hover:opacity-100" />
          </div>
        </button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed inset-0 z-50 flex items-center justify-center p-6 outline-none"
          onClick={() => setOpen(false)}
        >
          <Dialog.Title className="sr-only">{label ?? alt ?? "image"}</Dialog.Title>
          <div className="relative" onClick={(e) => e.stopPropagation()}>
            <Img src={src} alt={alt} sizes="92vw" maxWidth={2400}
                 className="max-h-[88vh] max-w-[92vw] rounded-[var(--radius-sm)] bg-transparent shadow-2xl"
                 imgClassName="max-h-[88vh] w-auto max-w-[92vw] object-contain" />
            <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-3 rounded-b-[var(--radius-sm)] bg-black/60 px-3 py-1.5 text-xs text-white/80">
              <span className="truncate">{label}</span>
              <a href={src} target="_blank" rel="noreferrer" className="flex shrink-0 items-center gap-1 hover:text-white">
                original <ExternalLink size={11} />
              </a>
            </div>
            <Dialog.Close aria-label="Close"
              className="absolute -right-3 -top-3 flex size-7 items-center justify-center rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--bg))] text-[hsl(var(--text-muted))] shadow-md transition-colors hover:text-[hsl(var(--text))]">
              <X size={13} />
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

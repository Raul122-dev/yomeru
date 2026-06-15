/**
 * ImageViewer — clickable image with lightbox/zoom overlay.
 * Usage: <ImageViewer src={url} alt="label" className="w-full" />
 */
import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X, ZoomIn } from "lucide-react";
import { cn } from "../../lib/utils";

interface ImageViewerProps {
  src: string;
  alt?: string;
  className?: string;
  label?: string;
}

export function ImageViewer({ src, alt, className, label }: ImageViewerProps) {
  const [open, setOpen] = useState(false);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          className={cn(
            "group relative block w-full overflow-hidden rounded border border-[hsl(var(--border))] cursor-zoom-in",
            className,
          )}
        >
          <img src={src} alt={alt} className="w-full object-cover" />
          <div className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/20 transition-all">
            <ZoomIn
              size={18}
              className="text-white opacity-0 group-hover:opacity-100 transition-opacity drop-shadow"
            />
          </div>
        </button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[92vh] max-w-[92vw] -translate-x-1/2 -translate-y-1/2 outline-none">
          <div className="relative">
            <img
              src={src}
              alt={alt}
              className="max-h-[88vh] max-w-[88vw] rounded object-contain shadow-2xl"
            />
            {label && (
              <div className="absolute bottom-0 left-0 right-0 rounded-b bg-black/60 px-3 py-1.5 text-[11px] text-white/80 text-center">
                {label}
              </div>
            )}
            <Dialog.Close className="absolute -right-3 -top-3 flex h-7 w-7 items-center justify-center rounded-full bg-[hsl(var(--bg))] border border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] shadow-md transition-colors">
              <X size={13} />
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

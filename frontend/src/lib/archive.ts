/**
 * Chapter archives (.cbz / .zip) unpacked in the browser: the pages become
 * ordinary image files for the page sorter, and a ComicInfo.xml inside (the
 * metadata comic library apps read) pre-fills the run's name, series and
 * chapter number.
 */
import { unzip } from "fflate";

const IMAGE_TYPES: Record<string, string> = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
};

export interface ArchiveInfo {
  title?: string;
  series?: string;
  number?: string;
}

interface Archive {
  pages: File[];
  info: ArchiveInfo;
}

export const isArchive = (f: File) => /\.(cbz|zip)$/i.test(f.name);

const ext = (path: string) => path.split(".").pop()?.toLowerCase() ?? "";
const base = (path: string) => path.split("/").pop() ?? path;
const hidden = (path: string) => path.split("/").some((part) => part.startsWith(".") || part === "__MACOSX");

/** Reading order: folders and numbers compared naturally (2.jpg before 10.jpg). */
const natural = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

function readInfo(xml: string): ArchiveInfo {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  const get = (tag: string) => doc.getElementsByTagName(tag)[0]?.textContent?.trim() || undefined;
  return { title: get("Title"), series: get("Series"), number: get("Number") };
}

export function readArchive(file: File): Promise<Archive> {
  return file.arrayBuffer().then(
    (buf) =>
      new Promise<Archive>((resolve, reject) => {
        unzip(new Uint8Array(buf), (err, entries) => {
          if (err) return reject(new Error(`${file.name} could not be opened: ${err.message}`));
          const names = Object.keys(entries).filter((n) => !n.endsWith("/") && !hidden(n));
          const pages = names
            .filter((n) => IMAGE_TYPES[ext(n)] && entries[n].length > 0)
            .sort(natural.compare)
            .map((n) => new File([entries[n] as BlobPart], base(n), { type: IMAGE_TYPES[ext(n)] }));
          const infoName = names.find((n) => base(n).toLowerCase() === "comicinfo.xml");
          const info = infoName ? readInfo(new TextDecoder().decode(entries[infoName])) : {};
          if (!pages.length) return reject(new Error(`${file.name} has no JPG, PNG or WebP pages`));
          resolve({ pages, info });
        });
      }),
  );
}

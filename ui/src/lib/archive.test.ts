import { describe, expect, it } from "vitest";
import { zipSync, strToU8 } from "fflate";
import { isArchive, readArchive } from "./archive";

const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2, 3]);
const zipFile = (entries: Record<string, Uint8Array>, name = "ch.cbz") =>
  new File([zipSync(entries) as BlobPart], name, { type: "application/zip" });

describe("readArchive", () => {
  it("keeps pages in natural order and skips what is not a page", async () => {
    const a = await readArchive(zipFile({
      "Vol 1/ch 2/10.png": png,
      "Vol 1/ch 2/2.png": png,
      "Vol 1/ch 2/1.jpg": new Uint8Array(),          // empty entry
      "__MACOSX/Vol 1/._2.png": png,
      "Vol 1/.DS_Store": png,
      "notes.txt": strToU8("hi"),
    }));
    expect(a.pages.map((p) => p.name)).toEqual(["2.png", "10.png"]);
    expect(a.pages[0].type).toBe("image/png");
    expect(a.info).toEqual({});
  });

  it("reads ComicInfo.xml", async () => {
    const xml = "<?xml version=\"1.0\"?><ComicInfo><Title>T</Title><Series>S</Series><Number>3</Number></ComicInfo>";
    const a = await readArchive(zipFile({ "001.jpg": png, "ComicInfo.xml": strToU8(xml) }));
    expect(a.info).toEqual({ title: "T", series: "S", number: "3" });
    expect(a.pages[0].type).toBe("image/jpeg");
  });

  it("rejects an archive without pages", async () => {
    await expect(readArchive(zipFile({ "a.txt": strToU8("x") }))).rejects.toThrow(/no JPG, PNG or WebP/);
  });

  it("recognises archives by extension", () => {
    expect(isArchive(new File([], "a.CBZ"))).toBe(true);
    expect(isArchive(new File([], "a.zip"))).toBe(true);
    expect(isArchive(new File([], "a.png"))).toBe(false);
  });
});

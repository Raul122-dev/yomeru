export const SOURCE_LANGUAGES = [
  { value: "auto", label: "Auto-detect" },
  { value: "Japanese", label: "Japanese" },
  { value: "Korean", label: "Korean" },
  { value: "Chinese (Simplified)", label: "Chinese (Simplified)" },
  { value: "Chinese (Traditional)", label: "Chinese (Traditional)" },
  { value: "English", label: "English" },
  { value: "Spanish", label: "Spanish" },
  { value: "Portuguese", label: "Portuguese" },
  { value: "French", label: "French" },
  { value: "German", label: "German" },
  { value: "Italian", label: "Italian" },
];

export const TARGET_LANGUAGES = SOURCE_LANGUAGES.filter(
  (l) => l.value !== "auto",
);

export const UI_LANGUAGES = [
  { value: "English", label: "English (default)" },
  { value: "Spanish", label: "Spanish" },
  { value: "Portuguese", label: "Portuguese" },
  { value: "French", label: "French" },
  { value: "German", label: "German" },
  { value: "Japanese", label: "Japanese" },
  { value: "Korean", label: "Korean" },
];

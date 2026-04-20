export type SectionId =
  | "core"
  | "schema"
  | "data-dictionary"
  | "diagrams"
  | "endpoints"
  | "lineage"
  | "guides";

export type SiteMetric = {
  label: string;
  value: string;
  note: string;
};

export type HeroSignal = {
  label: string;
  title: string;
  description: string;
};

export type QuickLink = {
  title: string;
  href: string;
  description: string;
};

export type SearchPrompt = {
  label: string;
  query: string;
  description: string;
};

export type AudienceLane = {
  label: string;
  title: string;
  href: string;
  description: string;
};

export type SectionStat = {
  label: string;
  value: string;
};

export type SectionMeta = {
  id: SectionId;
  label: string;
  eyebrow: string;
  cue: string;
  blurb: string;
  hubHref: string;
  stats: SectionStat[];
  quickLinks: QuickLink[];
  prompts: SearchPrompt[];
};

export type DocsContextRailMeta = {
  eyebrow: string;
  title: string;
  description: string;
  hubHref: string;
  hubLabel: string;
  links: QuickLink[];
  prompts: SearchPrompt[];
};

export type GeneratedPageGuideStep = {
  title: string;
  description: string;
};

export type GeneratedPageGuideCard = {
  label: string;
  title: string;
  description: string;
  href: string;
};

export type GeneratedPageFrameMeta = {
  eyebrow: string;
  title: string;
  description: string;
  stats: SiteMetric[];
  steps: GeneratedPageGuideStep[];
  generatorLabel: string;
  ownershipNote: string;
  regenerateCommand: string;
  modulesEyebrow: string;
  modulesTitle: string;
  modulesDescription: string;
  modules: GeneratedPageGuideCard[];
  links?: QuickLink[];
};

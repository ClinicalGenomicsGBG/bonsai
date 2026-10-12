import { BasketSample } from "../types";

export class BasketState {
  private name = "basket";
  private samples: Map<string, BasketSample> = new Map();
  private onChangeCallbacks: Set<(samples: BasketSample[]) => void> = new Set();

  constructor() {
    this.loadState();
  }

  onSelection(callback: (samples: BasketSample[]) => void): void {
    this.onChangeCallbacks.add(callback);
  }

  offSelection(callback: (samples: BasketSample[]) => void): void {
    this.onChangeCallbacks.delete(callback);
  }

  getSamples(): BasketSample[] {
    return Array.from(this.samples.values());
  }

  getSampleIds(): string[] {
    return this.getSamples().map((sample) => sample.sample_id);
  }

  addSamples(samples: BasketSample[]): void {
    samples.forEach((sample) => {
      if (sample.sample_id) {
        this.samples.set(sample.sample_id, sample);
      }
    });
    this.saveState();
    this.notifyChange();
  }

  removeSamples(sampleIds: string[]): void {
    sampleIds.forEach((id) => this.samples.delete(id));
    this.saveState();
    this.notifyChange();
  }

  clear(): void {
    this.samples.clear();
    this.saveState();
    this.notifyChange();
  }

  private notifyChange(): void {
    const selected = this.getSamples();
    this.onChangeCallbacks.forEach((callback) => callback(selected));
  }

  private saveState(): void {
    localStorage.setItem(this.storageKey, JSON.stringify(this.getSamples()));
  }

  private loadState(): void {
    const state = localStorage.getItem(this.storageKey);
    if (!state) return;

    try {
      const saved = JSON.parse(state) as unknown;
      if (!Array.isArray(saved)) return;

      saved.forEach((item) => {
        if (typeof item === "string") {
          // Backwards compatibility with baskets saved before full sample
          // objects were stored.
          this.samples.set(item, {
            sample_id: item,
            sample_name: item,
            assay: "",
          });
          return;
        }

        if (
          item &&
          typeof item === "object" &&
          "sample_id" in item &&
          typeof item.sample_id === "string"
        ) {
          this.samples.set(item.sample_id, item as BasketSample);
        }
      });
    } catch (e) {
      console.error("Failed to parse saved basket state", e);
    }
  }

  private get storageKey(): string {
    return `${this.name}_content`;
  }
}

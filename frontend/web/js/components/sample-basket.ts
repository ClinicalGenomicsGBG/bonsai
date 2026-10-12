import { BasketState } from "../state/basket-state";

export class BasketComponent extends HTMLElement {
  private state: BasketState;

  constructor(state: BasketState) {
    super();
    this.state = state;
    this.handleStateChange = this.handleStateChange.bind(this);
  }

  connectedCallback() {
    this.state.onSelection(this.handleStateChange);
    this.render();
  }

  disconnectedCallback() {
    this.state.offSelection(this.handleStateChange);
  }

  private handleStateChange() {
    this.render();
  }

  render() {
    this.innerHTML = "";
    const samples = this.state.getSamples();

    if (samples.length === 0) {
      this.innerHTML = "<p>Your basket is empty.</p>";
      return;
    }

    samples.forEach((sample) => {
      const item = document.createElement("div");
      item.className = "card mb-2 rounded-1 p-0 sample_in_basket";

      const body = document.createElement("div");
      body.className =
        "card-body py-1 d-flex flex-row justify-content-between align-items-center";

      const link = document.createElement("a");
      link.className = "text-muted d-flex flex-column";
      link.href = `${baseUrl}/sample/${sample.sample_id}`;

      const name = document.createElement("h6");
      name.id = sample.sample_id;
      name.className = "text-uppercase fw-bold text-muted my-0 py-0";
      name.textContent = sample.sample_name || sample.sample_id;

      const assay = document.createElement("i");
      assay.className = "text-muted fs-6 fw-light p-0";
      assay.textContent = typeof sample.assay === "string" ? sample.assay : "";

      const removeButton = document.createElement("button");
      removeButton.className =
        "float-end float-top btn btn-sm btn-outline-danger";
      removeButton.setAttribute("aria-label", "Remove");
      removeButton.type = "button";
      removeButton.dataset.id = sample.sample_id;
      removeButton.innerHTML = '<i class="bi bi-trash3-fill"></i>';

      link.append(name, assay);
      body.append(link, removeButton);
      item.appendChild(body);
      this.appendChild(item);
    });

    this.querySelectorAll<HTMLButtonElement>("button[data-id]").forEach(
      (button) => {
        button.addEventListener("click", () => {
          const id = button.dataset.id;
          if (id) this.state.removeSamples([id]);
        });
      },
    );
  }
}

customElements.define("basket-component", BasketComponent);

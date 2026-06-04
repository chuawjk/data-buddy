// DoneView — N3-S08
// Rendered when stage.changed(done) is received.
// Shows all accepted sections (in plan order) and a prominent export action.
//
// data-testid: done-view, done-section-list, done-section-item-{id}, done-export-button

import type { Section } from "../../types/api";

interface DoneViewProps {
  /** All plan sections — DoneView filters to accepted ones in plan order. */
  sections: Section[];
  /** Called when the user clicks Export. */
  onExport: () => void;
}

export default function DoneView({ sections, onExport }: DoneViewProps) {
  const acceptedSections = sections.filter((s) => s.status === "accepted");

  return (
    <div data-testid="done-view" className="flex flex-col gap-6">
      {/* Header */}
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-[#9b9489] mb-1">
          Complete
        </p>
        <h2 className="text-2xl font-serif font-light text-[#1a1a17]">Brief complete</h2>
        <p className="text-sm text-[#5d5a52] mt-1">
          Your brief has been built. Download it as a ZIP below.
        </p>
      </div>

      {/* Export button — prominent, at top */}
      <div>
        <button
          data-testid="done-export-button"
          type="button"
          onClick={onExport}
          className="flex items-center gap-2 bg-[#4a7a76] hover:bg-[#3b6460] text-white rounded-sm px-6 py-3 text-sm font-medium transition-colors"
        >
          <span aria-hidden="true">↓</span>
          <span>Export brief as ZIP</span>
        </button>
      </div>

      {/* Accepted sections list */}
      {acceptedSections.length > 0 && (
        <div
          data-testid="done-section-list"
          className="bg-white border border-[#ddd5c5] rounded overflow-hidden"
        >
          {acceptedSections.map((section, idx) => (
            <div
              key={section.id}
              data-testid={`done-section-item-${section.id}`}
              className={`flex items-center gap-3 px-4 py-3 border-b border-[#e8e1d1] last:border-0 text-sm ${
                idx % 2 === 0 ? "bg-white" : "bg-[#faf7f0]"
              }`}
            >
              <span className="text-[#9b9489] text-xs w-6 shrink-0">{idx + 1}</span>
              <span className="flex-1 font-medium text-[#1a1a17] break-words min-w-0">
                {section.title}
              </span>
              <span className="text-xs px-2 py-0.5 rounded-sm font-medium bg-[#d4edda] text-[#2d6a4f] shrink-0">
                accepted
              </span>
            </div>
          ))}
        </div>
      )}

      {acceptedSections.length === 0 && (
        <p className="text-sm text-[#9b9489]">No sections were accepted.</p>
      )}
    </div>
  );
}

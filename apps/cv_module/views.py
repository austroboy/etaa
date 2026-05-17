"""CV Module – Views.

New endpoints:
  GET  /api/cv/profiles/          – list all CandidateProfiles (search, filter)
  GET  /api/cv/profiles/<id>/     – single profile detail
  PATCH /api/cv/profiles/<id>/    – update remark / rejected_company / others / is_active
  GET  /api/cv/profiles/autocomplete/ – name/company/phone/email suggestions
  GET  /api/cv/jobs/              – existing CVRankingJob list
  GET  /api/cv/ui/                – serve the SPA HTML page
"""

import json
import os

from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from apps.cv_module.models import CVRankingJob, CandidateProfile


# ── Helpers ───────────────────────────────────────────────────────────────────

def _profile_to_dict(p: CandidateProfile) -> dict:
    return {
        "id":                    p.pk,
        "candidate_name":        p.candidate_name,
        "email":                 p.email,
        "phone":                 p.phone,
        "current_designation":   p.current_designation,
        "current_company":       p.current_company,
        "previous_designation":  p.previous_designation,
        "previous_company":      p.previous_company,
        "years_experience":      p.years_experience,
        "relevant_industries":   p.relevant_industries,
        "location":              p.location,
        "academic_qualification":p.academic_qualification,
        "key_qualifications":    p.key_qualifications,
        "summary":               p.summary,
        "match_score":           p.match_score,
        "rank":                  p.rank,
        "file_name":             p.file_name,
        "latest_job_id":         p.latest_job_id,
        # HR fields
        "remark":                p.remark,
        "rejected_company":      p.rejected_company,
        "others":                p.others,
        # Status
        "is_active":             p.is_active,
        # Timestamps
        "first_seen":            p.first_seen.isoformat(),
        "last_updated":          p.last_updated.isoformat(),
    }


# ── Profile List / Search ─────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name="dispatch")
class CandidateProfileListView(View):
    """
    GET  ?search=<term>  – search across name, company, phone, email
         ?is_active=true|false
         ?page=1&page_size=50
    """

    def get(self, request):
        qs = CandidateProfile.objects.all()

        search = request.GET.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(candidate_name__icontains=search)
                | Q(current_company__icontains=search)
                | Q(previous_company__icontains=search)
                | Q(phone__icontains=search)
                | Q(email__icontains=search)
            )

        active_param = request.GET.get("is_active", "")
        if active_param.lower() in {"true", "1"}:
            qs = qs.filter(is_active=True)
        elif active_param.lower() in {"false", "0"}:
            qs = qs.filter(is_active=False)

        total = qs.count()

        try:
            page      = max(1, int(request.GET.get("page", 1)))
            page_size = min(200, max(1, int(request.GET.get("page_size", 50))))
        except (TypeError, ValueError):
            page, page_size = 1, 50

        start = (page - 1) * page_size
        end   = start + page_size
        profiles = qs[start:end]

        return JsonResponse({
            "total":     total,
            "page":      page,
            "page_size": page_size,
            "results":   [_profile_to_dict(p) for p in profiles],
        })


# ── Profile Detail / Update ───────────────────────────────────────────────────

@method_decorator(csrf_exempt, name="dispatch")
class CandidateProfileDetailView(View):
    """
    GET   – full profile
    PATCH – update HR annotation fields (remark, rejected_company, others, is_active)
    """

    def _get_profile(self, pk):
        try:
            return CandidateProfile.objects.get(pk=pk)
        except CandidateProfile.DoesNotExist:
            return None

    def get(self, request, pk):
        profile = self._get_profile(pk)
        if profile is None:
            return JsonResponse({"error": "Not found"}, status=404)
        return JsonResponse(_profile_to_dict(profile))

    def patch(self, request, pk):
        profile = self._get_profile(pk)
        if profile is None:
            return JsonResponse({"error": "Not found"}, status=404)

        try:
            body = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        EDITABLE = {"remark", "rejected_company", "others", "is_active"}
        updated  = []
        for field in EDITABLE:
            if field in body:
                setattr(profile, field, body[field])
                updated.append(field)

        if updated:
            profile.save(update_fields=updated + ["last_updated"])

        return JsonResponse({"ok": True, "updated_fields": updated,
                             "profile": _profile_to_dict(profile)})


# ── Autocomplete ──────────────────────────────────────────────────────────────

class CandidateAutocompleteView(View):
    """
    GET ?q=<term>&field=name|company|phone|email
    Returns up to 10 distinct suggestions.
    """

    def get(self, request):
        q     = request.GET.get("q", "").strip()
        field = request.GET.get("field", "name")

        if not q or len(q) < 1:
            return JsonResponse({"suggestions": []})

        field_map = {
            "name":    "candidate_name",
            "company": "current_company",
            "phone":   "phone",
            "email":   "email",
        }
        db_field = field_map.get(field, "candidate_name")
        filter_kw = {f"{db_field}__icontains": q}

        values = (
            CandidateProfile.objects
            .filter(**filter_kw)
            .exclude(**{db_field: ""})
            .values_list(db_field, flat=True)
            .distinct()[:10]
        )
        return JsonResponse({"suggestions": list(values)})


# ── CVRankingJob List ─────────────────────────────────────────────────────────

class CVRankingJobListView(View):
    def get(self, request):
        jobs = CVRankingJob.objects.all()[:20]
        data = [
            {
                "id":         j.pk,
                "status":     j.status,
                "total_cvs":  j.total_cvs,
                "top_n":      j.top_n,
                "created_at": j.created_at.isoformat(),
                "output_zip": j.output_zip,
            }
            for j in jobs
        ]
        return JsonResponse({"jobs": data})


# ── SPA UI ────────────────────────────────────────────────────────────────────

class CVDashboardUIView(View):
    """Serve the candidate database SPA."""

    def get(self, request):
        html = _build_spa_html()
        return HttpResponse(html, content_type="text/html")


def _build_spa_html() -> str:
    """Generate the full SPA HTML for the CV candidate dashboard."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>CV Candidate Database – ETAA</title>
<style>
  :root{--blue:#1a56db;--blue-light:#e8f0fe;--green:#0f9d58;--red:#d93025;
        --grey:#f5f7fa;--border:#d1d5db;--text:#111827;--sub:#6b7280;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{font-family:system-ui,sans-serif;background:var(--grey);color:var(--text);}
  header{background:var(--blue);color:#fff;padding:14px 24px;display:flex;
         align-items:center;gap:12px;}
  header h1{font-size:1.2rem;font-weight:700;}
  .toolbar{display:flex;flex-wrap:wrap;gap:10px;padding:16px 24px;
           background:#fff;border-bottom:1px solid var(--border);
           align-items:center;}
  .search-wrap{position:relative;flex:1;min-width:200px;}
  .search-wrap input{width:100%;padding:8px 12px;border:1px solid var(--border);
    border-radius:6px;font-size:.9rem;outline:none;}
  .search-wrap input:focus{border-color:var(--blue);}
  .autocomplete-list{position:absolute;top:100%;left:0;right:0;background:#fff;
    border:1px solid var(--border);border-radius:0 0 6px 6px;z-index:99;
    max-height:200px;overflow-y:auto;display:none;}
  .autocomplete-list div{padding:8px 12px;cursor:pointer;font-size:.85rem;}
  .autocomplete-list div:hover{background:var(--blue-light);}
  select,button{padding:8px 14px;border:1px solid var(--border);border-radius:6px;
    font-size:.85rem;cursor:pointer;background:#fff;}
  button.primary{background:var(--blue);color:#fff;border:none;}
  .badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:.75rem;
         font-weight:600;}
  .badge.active{background:#d1fae5;color:#065f46;}
  .badge.inactive{background:#fee2e2;color:#991b1b;}
  .score{font-weight:700;color:var(--blue);}
  table{width:100%;border-collapse:collapse;font-size:.82rem;}
  th{background:#f0f4ff;text-align:left;padding:10px 12px;
     border-bottom:2px solid var(--border);white-space:nowrap;}
  td{padding:9px 12px;border-bottom:1px solid #e5e7eb;vertical-align:top;}
  td.trunc{max-width:240px;}
  tr:hover td{background:#fafbff;}
  .actions button{margin-right:4px;padding:4px 10px;font-size:.75rem;border-radius:4px;}
  .actions button.deact{background:#fee2e2;color:var(--red);border:1px solid #fca5a5;}
  .actions button.act{background:#d1fae5;color:var(--green);border:1px solid #6ee7b7;}
  .actions button.view-btn{background:var(--blue-light);color:var(--blue);
    border:1px solid #93c5fd;}
  /* Modal */
  .modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
    z-index:200;align-items:center;justify-content:center;}
  .modal-bg.open{display:flex;}
  .modal{background:#fff;border-radius:10px;width:min(720px,95vw);
    max-height:90vh;overflow-y:auto;padding:24px;position:relative;}
  .modal h2{font-size:1.1rem;margin-bottom:16px;color:var(--blue);}
  .modal .close{position:absolute;top:14px;right:18px;font-size:1.4rem;
    cursor:pointer;color:var(--sub);}
  .field-row{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;}
  .field-row.single{grid-template-columns:1fr;}
  label{display:block;font-size:.78rem;font-weight:600;color:var(--sub);
        margin-bottom:3px;}
  .field-val{font-size:.88rem;padding:4px 0;}
  textarea.edit{width:100%;padding:8px;border:1px solid var(--border);
    border-radius:6px;font-size:.85rem;resize:vertical;min-height:70px;}
  .save-btn{margin-top:14px;background:var(--blue);color:#fff;border:none;
    padding:9px 22px;border-radius:6px;cursor:pointer;font-size:.9rem;}
  .pagination{display:flex;gap:8px;align-items:center;justify-content:center;
    padding:16px;}
  .pagination button{padding:6px 14px;}
  .pagination button:disabled{opacity:.4;cursor:default;}
  .status-bar{padding:8px 24px;font-size:.8rem;color:var(--sub);}
  .empty{text-align:center;padding:48px;color:var(--sub);}
</style>
</head>
<body>

<header>
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#fff"
       stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
    <circle cx="9" cy="7" r="4"/>
    <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
    <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
  </svg>
  <h1>CV Candidate Database</h1>
</header>

<div class="toolbar">
  <select id="searchField">
    <option value="name">Name</option>
    <option value="company">Company</option>
    <option value="phone">Phone</option>
    <option value="email">Email</option>
  </select>
  <div class="search-wrap">
    <input id="searchInput" type="text" placeholder="Search candidates…" autocomplete="off"/>
    <div class="autocomplete-list" id="acList"></div>
  </div>
  <select id="statusFilter">
    <option value="">All Status</option>
    <option value="true">Active</option>
    <option value="false">Inactive</option>
  </select>
  <button class="primary" onclick="loadProfiles(1)">Search</button>
  <button onclick="clearSearch()">Clear</button>
  <span id="totalBadge" style="margin-left:auto;font-size:.82rem;color:var(--sub);"></span>
</div>

<div class="status-bar" id="statusBar"></div>

<div style="overflow-x:auto;padding:0 0 0 0;">
<table id="profileTable">
  <thead>
    <tr>
      <th>#</th><th>Name</th><th>Score</th>
      <th>Current Designation</th><th>Current Company</th>
      <th>Previous Designation</th><th>Previous Company</th>
      <th>Exp</th><th>Industries</th><th>Location</th>
      <th>Email</th><th>Phone</th>
      <th>Academic</th>
      <th>Key Qualifications</th><th>Summary</th>
      <th>Remark</th><th>Rejected Company</th><th>Others</th>
      <th>File</th><th>First Seen</th><th>Last Updated</th>
      <th>Status</th><th>Actions</th>
    </tr>
  </thead>
  <tbody id="tableBody"></tbody>
</table>
</div>
<div class="empty" id="emptyMsg" style="display:none">No candidates found.</div>

<div class="pagination">
  <button id="prevBtn" onclick="changePage(-1)" disabled>← Prev</button>
  <span id="pageInfo">Page 1</span>
  <button id="nextBtn" onclick="changePage(1)">Next →</button>
</div>

<!-- Detail / Edit Modal -->
<div class="modal-bg" id="modalBg">
  <div class="modal">
    <span class="close" onclick="closeModal()">✕</span>
    <h2 id="modalTitle">Candidate Profile</h2>
    <div id="modalBody"></div>
  </div>
</div>

<script>
const API = '/api/cv/profiles/';
let currentPage = 1, totalPages = 1, pageSize = 50;
let acTimer = null;

async function loadProfiles(page=1) {
  currentPage = page;
  const search = document.getElementById('searchInput').value.trim();
  const field  = document.getElementById('searchField').value;
  const active = document.getElementById('statusFilter').value;
  let url = `${API}?page=${page}&page_size=${pageSize}`;
  if (search) url += `&search=${encodeURIComponent(search)}`;
  if (active !== '') url += `&is_active=${active}`;
  document.getElementById('statusBar').textContent = 'Loading…';
  try {
    const res  = await fetch(url);
    const data = await res.json();
    renderTable(data);
  } catch(e) {
    document.getElementById('statusBar').textContent = 'Error loading data.';
  }
}

function renderTable(data) {
  const tbody = document.getElementById('tableBody');
  tbody.innerHTML = '';
  const empty = document.getElementById('emptyMsg');
  const total = data.total || 0;
  totalPages = Math.max(1, Math.ceil(total / pageSize));
  document.getElementById('totalBadge').textContent = `${total} candidate(s)`;
  document.getElementById('pageInfo').textContent =
    `Page ${currentPage} / ${totalPages}`;
  document.getElementById('prevBtn').disabled = currentPage <= 1;
  document.getElementById('nextBtn').disabled = currentPage >= totalPages;
  document.getElementById('statusBar').textContent =
    `Showing ${data.results.length} of ${total} candidates`;

  if (!data.results.length) { empty.style.display=''; return; }
  empty.style.display = 'none';

  data.results.forEach((p, i) => {
    const tr = document.createElement('tr');
    const offset = (currentPage - 1) * pageSize;
    // Helpers for long text columns: truncate with tooltip showing full text.
    const truncTd = (val, max) => {
      const s = String(val || '');
      const safe = esc(s);
      const shown = s.length > max ? esc(s.slice(0, max)) + '…' : safe;
      return `<td title="${safe}" class="trunc">${shown}</td>`;
    };
    const fmtDate = (iso) => {
      if (!iso) return '';
      const d = new Date(iso);
      if (isNaN(d)) return esc(iso);
      return d.toLocaleDateString() + ' ' +
             d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
    };
    tr.innerHTML = `
      <td>${offset + i + 1}</td>
      <td><strong>${esc(p.candidate_name)}</strong></td>
      <td><span class="score">${p.match_score}</span></td>
      <td>${esc(p.current_designation)}</td>
      <td>${esc(p.current_company)}</td>
      <td>${esc(p.previous_designation)}</td>
      <td>${esc(p.previous_company)}</td>
      <td>${p.years_experience} yr${p.years_experience!==1?'s':''}</td>
      <td>${esc(p.relevant_industries)}</td>
      <td>${esc(p.location)}</td>
      <td>${esc(p.email)}</td>
      <td>${esc(p.phone)}</td>
      <td>${esc(p.academic_qualification)}</td>
      ${truncTd(p.key_qualifications, 60)}
      ${truncTd(p.summary, 80)}
      ${truncTd(p.remark, 60)}
      ${truncTd(p.rejected_company, 60)}
      ${truncTd(p.others, 60)}
      <td>${esc(p.file_name)}</td>
      <td>${fmtDate(p.first_seen)}</td>
      <td>${fmtDate(p.last_updated)}</td>
      <td><span class="badge ${p.is_active?'active':'inactive'}">
        ${p.is_active?'Active':'Inactive'}</span></td>
      <td class="actions">
        <button class="view-btn" onclick="openProfile(${p.id})">View</button>
        <button class="${p.is_active?'deact':'act'}"
          onclick="toggleActive(${p.id},${!p.is_active})">
          ${p.is_active?'Deactivate':'Activate'}
        </button>
      </td>`;
    tbody.appendChild(tr);
  });
}

function changePage(dir) {
  const np = currentPage + dir;
  if (np < 1 || np > totalPages) return;
  loadProfiles(np);
}

function clearSearch() {
  document.getElementById('searchInput').value = '';
  document.getElementById('statusFilter').value = '';
  loadProfiles(1);
}

// ── Autocomplete ──────────────────────────────────────────────────────────
document.getElementById('searchInput').addEventListener('input', function() {
  clearTimeout(acTimer);
  const q = this.value.trim();
  if (q.length < 2) { hideAc(); return; }
  acTimer = setTimeout(() => fetchAc(q), 250);
});
document.getElementById('searchInput').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') { hideAc(); loadProfiles(1); }
});
document.addEventListener('click', (e) => {
  if (!e.target.closest('.search-wrap')) hideAc();
});
async function fetchAc(q) {
  const field = document.getElementById('searchField').value;
  const res = await fetch(`${API}autocomplete/?q=${encodeURIComponent(q)}&field=${field}`);
  const data = await res.json();
  showAc(data.suggestions || []);
}
function showAc(items) {
  const list = document.getElementById('acList');
  list.innerHTML = '';
  if (!items.length) { hideAc(); return; }
  items.forEach(s => {
    const d = document.createElement('div');
    d.textContent = s;
    d.onclick = () => {
      document.getElementById('searchInput').value = s;
      hideAc();
      loadProfiles(1);
    };
    list.appendChild(d);
  });
  list.style.display = 'block';
}
function hideAc() {
  document.getElementById('acList').style.display = 'none';
}

// ── Toggle Active ─────────────────────────────────────────────────────────
async function toggleActive(id, active) {
  await fetch(`${API}${id}/`, {
    method:'PATCH',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({is_active: active}),
  });
  loadProfiles(currentPage);
}

// ── Profile Modal ─────────────────────────────────────────────────────────
let currentProfileId = null;
async function openProfile(id) {
  currentProfileId = id;
  const res = await fetch(`${API}${id}/`);
  const p   = await res.json();
  document.getElementById('modalTitle').textContent =
    p.candidate_name || 'Candidate Profile';
  document.getElementById('modalBody').innerHTML = buildModalHtml(p);
  document.getElementById('modalBg').classList.add('open');
}
function closeModal() {
  document.getElementById('modalBg').classList.remove('open');
}
function buildModalHtml(p) {
  return `
    <div class="field-row">
      <div><label>Score</label><div class="field-val score">${p.match_score}/100</div></div>
      <div><label>Status</label><div class="field-val">
        <span class="badge ${p.is_active?'active':'inactive'}">${p.is_active?'Active':'Inactive'}</span>
      </div></div>
    </div>
    <div class="field-row">
      <div><label>Current Designation</label><div class="field-val">${esc(p.current_designation)}</div></div>
      <div><label>Current Company</label><div class="field-val">${esc(p.current_company)}</div></div>
    </div>
    <div class="field-row">
      <div><label>Previous Designation</label><div class="field-val">${esc(p.previous_designation)}</div></div>
      <div><label>Previous Company</label><div class="field-val">${esc(p.previous_company)}</div></div>
    </div>
    <div class="field-row">
      <div><label>Experience</label><div class="field-val">${p.years_experience} yrs</div></div>
      <div><label>Location</label><div class="field-val">${esc(p.location)}</div></div>
    </div>
    <div class="field-row">
      <div><label>Email</label><div class="field-val">${esc(p.email)}</div></div>
      <div><label>Phone</label><div class="field-val">${esc(p.phone)}</div></div>
    </div>
    <div class="field-row">
      <div><label>Academic Qualification</label>
        <div class="field-val">${esc(p.academic_qualification)}</div></div>
      <div><label>Relevant Industries</label>
        <div class="field-val">${esc(p.relevant_industries)}</div></div>
    </div>
    <div class="field-row single">
      <div><label>Key Qualifications</label>
        <div class="field-val" style="white-space:pre-wrap">${esc(p.key_qualifications)}</div></div>
    </div>
    <div class="field-row single">
      <div><label>Summary</label>
        <div class="field-val" style="white-space:pre-wrap">${esc(p.summary)}</div></div>
    </div>
    <hr style="margin:16px 0;border:none;border-top:1px solid var(--border)"/>
    <h3 style="font-size:.9rem;margin-bottom:10px;color:var(--sub)">HR Annotations</h3>
    <div class="field-row single">
      <div><label>Remark</label>
        <textarea class="edit" id="ed_remark">${esc(p.remark)}</textarea></div>
    </div>
    <div class="field-row single">
      <div><label>Rejected Company</label>
        <textarea class="edit" id="ed_rejected_company">${esc(p.rejected_company)}</textarea></div>
    </div>
    <div class="field-row single">
      <div><label>Others</label>
        <textarea class="edit" id="ed_others">${esc(p.others)}</textarea></div>
    </div>
    <button class="save-btn" onclick="saveAnnotations()">💾 Save Annotations</button>
    <span id="saveStatus" style="margin-left:12px;font-size:.82rem;color:var(--green)"></span>
  `;
}
async function saveAnnotations() {
  const payload = {
    remark:           document.getElementById('ed_remark').value,
    rejected_company: document.getElementById('ed_rejected_company').value,
    others:           document.getElementById('ed_others').value,
  };
  const res = await fetch(`${API}${currentProfileId}/`, {
    method:'PATCH',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  document.getElementById('saveStatus').textContent =
    data.ok ? '✓ Saved' : '✗ Error';
  setTimeout(() => {
    const el = document.getElementById('saveStatus');
    if (el) el.textContent = '';
  }, 2500);
}

function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Init
loadProfiles(1);
</script>
</body>
</html>"""
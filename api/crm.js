// /api/crm — passcode-gated outreach CRM (call tracking for the AI agency pilot list).
// Not linked from the public site; auth is a shared passcode, not a per-user login.
//
// GET  /api/crm?passcode=XXX                      -> { contacts:[...], calls:[...] }
// POST /api/crm  { passcode, action, ... }
//   action: "add_contact"    { company, phone, email, what_they_do, contact_name, contact_title, confidence }
//   action: "update_contact" { id, ...any of the add_contact fields, status, next_follow_up }
//   action: "delete_contact" { id }
//   action: "log_call"       { contact_id, called_by, response, notes, status? }  (status optionally updates the contact)
//   action: "delete_call"    { id }
import { getSql, cors, readBody } from "./_db.js";

const SEED_CONTACTS = [
  { company: "A I Associates Pte. Ltd.", phone: "6659 7688", email: "admin@ai-associates.com", what_they_do: "Interior design & build, furniture", contact_name: "Benz Tangkunboriboon", contact_title: "Managing Director", confidence: "High" },
  { company: "Xpress Surveys & FMC Pte. Ltd.", phone: "9170 0500", email: "info@xpresssurvey.com", what_they_do: "Building/UAV survey, fire safety, marine supplies", contact_name: "David Haw", contact_title: "Director", confidence: "Medium" },
  { company: "Swimwerks Asia Pte. Ltd.", phone: "6805 8186", email: "herron@swimwerks.com.sg", what_they_do: "Aquatics/lifeguard training, sports safety equipment", contact_name: "Herron Ho", contact_title: "Founder", confidence: "High" },
  { company: "C+H Associates Pte. Ltd.", phone: "6452 7727", email: "contact@chassociatespl.com", what_they_do: "AV/photo equipment, fire safety, event mgmt, security", contact_name: "Alice Loh", contact_title: "Director", confidence: "High" },
  { company: "Genesis Artech Pte. Ltd.", phone: "8113 0288", email: "bernie@genesisartech.com", what_they_do: "Event management, storage, transportation", contact_name: "Tan Aik Beng (\"Daniel Tan\")", contact_title: "Key principal (title unconfirmed)", confidence: "Low" },
  { company: "Transland Singapore Pte. Ltd.", phone: "6560 8032", email: "carrie@transland.com.sg", what_they_do: "Childcare/social services, transportation", contact_name: "", contact_title: "Not found — ask for the Director", confidence: "" },
  { company: "Hsen Global Pte. Ltd.", phone: "9060 8460", email: "globalhsen@yahoo.com.sg", what_they_do: "Events/decor, furniture, childcare, PR", contact_name: "", contact_title: "Not found — ask for the owner/Director", confidence: "" },
  { company: "Hexo 360 Pte. Ltd.", phone: "6447 9904", email: "alicia@hexogonsol.com", what_they_do: "AV products, event management, consulting", contact_name: "Adrian Goh", contact_title: "Group Managing Director (parent Hexogon Group)", confidence: "Medium" },
  { company: "Fishermen Integrated Pte. Ltd.", phone: "+65 9152 8149", email: "adam@fishermen.co", what_they_do: "Advertising/graphics, PR, brand consulting", contact_name: "Adam Miranda", contact_title: "Co-Founder & Executive Creative Director", confidence: "High" },
  { company: "Direct Funeral Services Pte. Ltd.", phone: "6299 4523", email: "info@directfuneral.com.sg", what_they_do: "Funeral services", contact_name: "Jenny Tay", contact_title: "Managing Director", confidence: "High" },
  { company: "Sobono Energy Private Limited", phone: "6773 0219", email: "weekhoon.oh@sobono.com.sg", what_they_do: "Domestic equipment, energy consulting", contact_name: "Oh Wee Khoon", contact_title: "Founder & Managing Director", confidence: "High" },
  { company: "Total Well-Being SG Limited", phone: "9721 3150", email: "weetin.hong@twbsg.org", what_they_do: "Childcare/social services, training (charity/non-profit)", contact_name: "\"Wee Tin\" (email contact)", contact_title: "Unconfirmed — board-run charity", confidence: "Low" },
  { company: "On Trust Maintenance Pte. Ltd.", phone: "6513 3163", email: "ikhsanosman@ontrustms.com", what_they_do: "Cleaning, laundry, waste disposal", contact_name: "Ikhsan Osman", contact_title: "Director", confidence: "High" },
  { company: "Mastereign Professionals Pte. Ltd.", phone: "6836 6466", email: "jerome@mastereign.com", what_they_do: "Event mgmt, PR, childcare, F&B, advertising", contact_name: "Terry Lim (or Jerome Gan as backup)", contact_title: "Managing Director", confidence: "Medium" },
  { company: "Transco-Pac Transport & Environmental Pte. Ltd.", phone: "6897 7110", email: "accadmin@transcopac.com", what_they_do: "Transportation, scrap dealing, waste disposal", contact_name: "Keith Ang", contact_title: "Founder & Managing Director", confidence: "High" },
  { company: "Chiap Seng Enterprises Pte. Ltd.", phone: "8898 3830", email: "issac@chiapseng.com.sg", what_they_do: "Furniture/hardware, event mgmt, transportation", contact_name: "Issac Heng", contact_title: "Possibly Project Manager, not owner (unconfirmed)", confidence: "Low" },
];

async function ensureSchema(sql) {
  await sql`
    CREATE TABLE IF NOT EXISTS crm_contacts (
      id              SERIAL PRIMARY KEY,
      company         TEXT NOT NULL,
      phone           TEXT,
      email           TEXT,
      what_they_do    TEXT,
      contact_name    TEXT,
      contact_title   TEXT,
      confidence      TEXT,
      status          TEXT NOT NULL DEFAULT 'not_called',
      next_follow_up  DATE,
      created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `;
  await sql`
    CREATE TABLE IF NOT EXISTS crm_calls (
      id          SERIAL PRIMARY KEY,
      contact_id  INTEGER NOT NULL REFERENCES crm_contacts(id) ON DELETE CASCADE,
      called_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
      called_by   TEXT,
      response    TEXT,
      notes       TEXT,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `;

  const [{ n }] = await sql`SELECT count(*)::int AS n FROM crm_contacts`;
  if (n === 0) {
    for (const c of SEED_CONTACTS) {
      await sql`
        INSERT INTO crm_contacts (company, phone, email, what_they_do, contact_name, contact_title, confidence)
        VALUES (${c.company}, ${c.phone}, ${c.email}, ${c.what_they_do}, ${c.contact_name}, ${c.contact_title}, ${c.confidence})
      `;
    }
    // Seed the call already made: Fishermen Integrated — Adam took the call.
    const [fishermen] = await sql`SELECT id FROM crm_contacts WHERE company = 'Fishermen Integrated Pte. Ltd.'`;
    if (fishermen) {
      await sql`
        INSERT INTO crm_calls (contact_id, response, notes)
        VALUES (${fishermen.id}, 'Spoke with contact', 'Adam took the call.')
      `;
      await sql`UPDATE crm_contacts SET status = 'contacted' WHERE id = ${fishermen.id}`;
    }
  }
}

function checkPasscode(req, body) {
  const expected = process.env.CRM_PASSCODE || "1234321";
  const given = (body && body.passcode) || req.query.passcode || "";
  return String(given) === String(expected);
}

export default async function handler(req, res) {
  if (cors(req, res)) return;

  const body = req.method === "POST" ? readBody(req) : null;
  if (!checkPasscode(req, body)) {
    res.status(401).json({ error: "Unauthorized" });
    return;
  }

  try {
    const sql = getSql();
    await ensureSchema(sql);

    if (req.method === "GET") {
      const contacts = await sql`SELECT * FROM crm_contacts ORDER BY company ASC`;
      const calls = await sql`SELECT * FROM crm_calls ORDER BY called_at DESC`;
      res.setHeader("Cache-Control", "no-store");
      res.status(200).json({ contacts, calls });
      return;
    }

    if (req.method === "POST") {
      const action = body.action || "";

      if (action === "add_contact") {
        const [row] = await sql`
          INSERT INTO crm_contacts (company, phone, email, what_they_do, contact_name, contact_title, confidence)
          VALUES (${body.company || ""}, ${body.phone || ""}, ${body.email || ""}, ${body.what_they_do || ""},
                  ${body.contact_name || ""}, ${body.contact_title || ""}, ${body.confidence || ""})
          RETURNING *
        `;
        res.status(200).json({ contact: row });
        return;
      }

      if (action === "update_contact") {
        const id = Number(body.id);
        if (!id) { res.status(400).json({ error: "Missing id" }); return; }
        const [row] = await sql`
          UPDATE crm_contacts SET
            company = COALESCE(${body.company}, company),
            phone = COALESCE(${body.phone}, phone),
            email = COALESCE(${body.email}, email),
            what_they_do = COALESCE(${body.what_they_do}, what_they_do),
            contact_name = COALESCE(${body.contact_name}, contact_name),
            contact_title = COALESCE(${body.contact_title}, contact_title),
            confidence = COALESCE(${body.confidence}, confidence),
            status = COALESCE(${body.status}, status),
            next_follow_up = COALESCE(${body.next_follow_up || null}, next_follow_up)
          WHERE id = ${id}
          RETURNING *
        `;
        res.status(200).json({ contact: row });
        return;
      }

      if (action === "delete_contact") {
        const id = Number(body.id);
        if (!id) { res.status(400).json({ error: "Missing id" }); return; }
        await sql`DELETE FROM crm_contacts WHERE id = ${id}`;
        res.status(200).json({ ok: true });
        return;
      }

      if (action === "log_call") {
        const contactId = Number(body.contact_id);
        if (!contactId) { res.status(400).json({ error: "Missing contact_id" }); return; }
        const [call] = await sql`
          INSERT INTO crm_calls (contact_id, called_by, response, notes)
          VALUES (${contactId}, ${body.called_by || ""}, ${body.response || ""}, ${body.notes || ""})
          RETURNING *
        `;
        if (body.status) {
          await sql`UPDATE crm_contacts SET status = ${body.status} WHERE id = ${contactId}`;
        }
        if (body.next_follow_up !== undefined) {
          await sql`UPDATE crm_contacts SET next_follow_up = ${body.next_follow_up || null} WHERE id = ${contactId}`;
        }
        res.status(200).json({ call });
        return;
      }

      if (action === "delete_call") {
        const id = Number(body.id);
        if (!id) { res.status(400).json({ error: "Missing id" }); return; }
        await sql`DELETE FROM crm_calls WHERE id = ${id}`;
        res.status(200).json({ ok: true });
        return;
      }

      res.status(400).json({ error: "Unknown action" });
      return;
    }

    res.status(405).json({ error: "Method not allowed" });
  } catch (e) {
    console.error("crm error", e);
    res.status(500).json({ error: "Server error" });
  }
}

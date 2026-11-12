import React, { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Building2, ChevronDown, ChevronUp, HelpCircle, Mail, Search, Send, ShieldCheck, Target } from "lucide-react";
import { api } from "@/lib/api";
import { Button, Card, Input, notify, PageHeader } from "@/components/kit";
import { BrandLogo, Page } from "@/components/Layout";

const POINTS = [
  { icon: Target, title: "Our objective", desc: "Reduce the time candidates spend searching across LinkedIn, portals, WhatsApp groups and company websites." },
  { icon: Search, title: "Curated intelligence", desc: "Jobs are curated from publicly available and legitimate sources into one premium collection." },
  { icon: Send, title: "Direct applications", desc: "Candidates apply directly to employers using the provided links and public contact details." },
  { icon: ShieldCheck, title: "Honest positioning", desc: "We do not guarantee interviews, selection or employment — we provide discovery, not promises." },
];

export function About() {
  return (
    <Page>
      <BrandLogo />
      <h1 className="h-page mt-8">A premium career intelligence platform</h1>
      <p className="mt-4 max-w-2xl text-gray-600">
        JobRadar is powered by <b className="text-brand">Evolveminds</b>. Instead of spending hours searching everywhere, members access a curated collection of relevant opportunities in one place.
      </p>
      <div className="mt-10 grid gap-5 md:grid-cols-2">
        {POINTS.map((p) => (
          <Card key={p.title} className="p-7" data-testid={`about-${p.title}`}>
            <p.icon className="h-6 w-6 text-brand" />
            <p className="mt-3 font-extrabold">{p.title}</p>
            <p className="mt-1 text-sm text-gray-600">{p.desc}</p>
          </Card>
        ))}
      </div>
    </Page>
  );
}

const FAQS = [
  ["What is JobRadar?", "JobRadar is a curated job-discovery platform by Evolveminds. We collect relevant job opportunities from public sources so you can discover and apply faster."],
  ["Is this a recruitment agency?", "No. JobRadar is not a recruitment agency or marketplace. We provide curated job information for discovery only; you apply directly to employers."],
  ["Does membership guarantee a job?", "No. Membership provides access to curated job information and platform features. It does not guarantee interviews, selection, employment or any response from employers."],
  ["How do I apply for a job?", "Open any job as an active member and click Apply Now to reach the employer's official application link or public contact details."],
  ["Can I cancel my membership?", "Yes. You can cancel anytime; your access continues until the current expiry date."],
  ["What happens when my membership expires?", "Your account, saved jobs and payment history are retained, but premium job details are locked until you renew."],
  ["Can I renew before expiry?", "Yes. If you renew early, the new duration is added on top of your remaining days — you never lose active time."],
  ["Are all jobs verified?", "Jobs are curated from publicly available sources and carry a quality indicator, but candidates should always verify details independently."],
  ["Can I get a refund?", "Membership fees are generally non-refundable once premium access is activated. Please review our Refund Policy."],
  ["How do I contact support?", "Use the Contact page to reach our support team."],
];

export function FAQ() {
  const [open, setOpen] = useState(0);
  return (
    <Page narrow>
      <PageHeader title="Frequently Asked Questions" />
      <div className="space-y-3">
        {FAQS.map(([q, a], i) => (
          <Card key={q} className="cursor-pointer py-4" onClick={() => setOpen(open === i ? null : i)} data-testid={`faq-${i}`}>
            <div className="flex items-center justify-between gap-4">
              <p className="font-bold text-gray-900">{q}</p>
              {open === i ? <ChevronUp className="h-5 w-5 text-brand" /> : <ChevronDown className="h-5 w-5 text-gray-400" />}
            </div>
            {open === i ? <p className="mt-3 text-sm leading-relaxed text-gray-600">{a}</p> : null}
          </Card>
        ))}
      </div>
    </Page>
  );
}

const SUPPORT_EMAIL = "support@evolveminds.com";

export function Contact() {
  const [form, setForm] = useState({ name: "", email: "", message: "" });
  const [loading, setLoading] = useState(false);
  const bind = (k) => ({ value: form[k], onChange: (e) => setForm((f) => ({ ...f, [k]: e.target.value })) });
  const submit = async () => {
    if (!form.name || !form.email || !form.message) return notify("Please fill all fields", "error");
    setLoading(true);
    try {
      await api("/contact", { method: "POST", body: form, auth: false });
      notify("Message sent! We'll be in touch.", "success");
      setForm({ name: "", email: "", message: "" });
    } catch {
      notify("Failed to send message", "error");
    } finally {
      setLoading(false);
    }
  };
  return (
    <Page>
      <PageHeader title="Get in touch" />
      <div className="grid gap-8 lg:grid-cols-[360px_1fr]">
        <Card className="h-fit space-y-4">
          <p className="flex items-center gap-3 font-bold"><Building2 className="h-5 w-5 text-brand" />Evolveminds</p>
          <a href={`mailto:${SUPPORT_EMAIL}`} className="flex items-center gap-3 font-semibold text-brand hover:underline" data-testid="contact-email-link"><Mail className="h-5 w-5" />{SUPPORT_EMAIL}</a>
          <Link to="/faq" className="flex items-center gap-3 font-semibold text-brand hover:underline" data-testid="contact-faq-link"><HelpCircle className="h-5 w-5" />Visit our FAQ</Link>
        </Card>
        <Card className="space-y-4 p-8">
          <h2 className="h-sec">Send us a message</h2>
          <div className="grid gap-4 md:grid-cols-2">
            <Input label="Name" {...bind("name")} data-testid="contact-name" />
            <Input label="Email" type="email" {...bind("email")} data-testid="contact-email" />
          </div>
          <Input label="Message" multiline rows={5} {...bind("message")} data-testid="contact-message" />
          <Button title="Send Message" loading={loading} onClick={submit} data-testid="contact-submit" />
        </Card>
      </div>
    </Page>
  );
}

const DISCLAIMER = "JobRadar by Evolveminds provides curated job information for discovery purposes only. We do not guarantee interviews, selection, employment, salary, or response from employers. Candidates are responsible for applying directly and verifying job information.";
const CONTENT = {
  terms: { title: "Terms & Conditions", body: [
    "By using JobRadar by Evolveminds, you agree to these Terms. JobRadar is a paid curated job-discovery membership platform operated by Evolveminds.",
    "Membership fees provide access to curated job information and platform features. Membership does not guarantee an interview, job offer, employment, salary, or response from any employer.",
    "Jobs are curated from publicly available and legitimate sources. Candidates apply directly to employers and are responsible for verifying all job information.",
    "You agree to use the platform lawfully and not to misuse, scrape, or resell curated content.",
    "Evolveminds may update plans, pricing, and features from time to time.",
  ] },
  privacy: { title: "Privacy Policy", body: [
    "We collect the information you provide during registration (name, email, mobile, preferences) to operate your account and personalise your experience.",
    "We use your email to send transactional and membership-related notifications.",
    "We do not sell your personal data. We may share limited data with service providers strictly to operate the platform.",
    "You can update your profile or request account changes at any time through the app.",
  ] },
  refund: { title: "Refund Policy", body: [
    "Membership fees are generally non-refundable once premium access has been activated, as access to curated content is granted immediately.",
    "If a payment was charged in error or a technical issue prevented access, contact support and we will review your case.",
    "Demo transactions carry no real charge and are not eligible for refunds.",
  ] },
  cancellation: { title: "Cancellation Policy", body: [
    "You may cancel your membership at any time. Your premium access will continue until the current expiry date.",
    "In demo mode, memberships do not auto-renew. When a real payment gateway is enabled, cancellation stops future renewals.",
    "Your account, saved jobs, and payment history are retained after cancellation.",
  ] },
  disclaimer: { title: "Disclaimer", body: [
    DISCLAIMER,
    "JobRadar is not a recruitment agency or marketplace and does not control any employer's application or hiring process.",
    "We do not claim that an application was successfully submitted unless the external employer confirms it.",
  ] },
};

export function Legal() {
  const { type } = useParams();
  const navigate = useNavigate();
  const key = CONTENT[type] ? type : "terms";
  const data = CONTENT[key];
  return (
    <Page>
      <div className="grid gap-10 lg:grid-cols-[240px_1fr]">
        <nav className="space-y-1 lg:sticky lg:top-24 lg:self-start">
          {Object.keys(CONTENT).map((k) => (
            <button key={k} onClick={() => navigate(`/legal/${k}`)} data-testid={`legal-tab-${k}`}
              className={`nav-link block w-full text-left ${k === key ? "nav-link-active" : ""}`}>{CONTENT[k].title}</button>
          ))}
        </nav>
        <div className="max-w-3xl">
          <h1 className="h-page" data-testid="legal-title">{data.title}</h1>
          <div className="mt-8 space-y-4">
            {data.body.map((p, i) => <p key={i} className="leading-relaxed text-gray-600">{p}</p>)}
          </div>
        </div>
      </div>
    </Page>
  );
}

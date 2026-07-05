from __future__ import annotations

import sys
import re
from pathlib import Path
from typing import Any
from playwright.sync_api import Page
from .models import ApplicationPacket, JobListing, Profile

class JobApplier:
    def __init__(self, page: Page, packet: ApplicationPacket, profile: Profile, resume_path: Path):
        self.page = page
        self.packet = packet
        self.profile = profile
        self.resume_path = resume_path
        self.form_answers = packet.form_answers or {}
        # Normalize form answer keys to lowercase for robust mapping
        self.normalized_answers = {str(k).lower().strip(): str(v).strip() for k, v in self.form_answers.items()}

    def execute_application(self) -> dict[str, Any]:
        """
        Executes the direct application process by navigating to the job page,
        clicking the apply button, and stepping through the modal form pages.
        """
        url = self.packet.job.url
        print(f"[Applier] Navigating to: {url}")
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"[Applier] Navigation error: {e}")
            return {"success": False, "reason": f"Navigation error: {e}"}
        
        self.page.wait_for_timeout(3000)

        # 1. Click apply button
        clicked_apply = self._find_and_click_apply_button()
        if not clicked_apply:
            return {"success": False, "reason": "Apply button not found or not visible"}

        self.page.wait_for_timeout(2000)

        # 2. Loop to fill forms page by page
        max_steps = 15
        step = 0
        while step < max_steps:
            step += 1
            print(f"[Applier] Processing form page {step}...")
            
            # Check if we are at the final review page
            if self._is_review_page():
                print("[Applier] Reached the final review page. Safe draft saved!")
                return {"success": True, "draft_saved": True, "reason": "Reached review page (draft)"}

            # Fill inputs on the current screen
            self._fill_visible_inputs()

            # Click next button
            clicked_next = self._click_next_button()
            if not clicked_next:
                # If we couldn't click next, maybe there's a submit button or we are done?
                print("[Applier] No next button found. Form filling complete or stuck.")
                break
            
            self.page.wait_for_timeout(2000)

        return {"success": True, "draft_saved": True, "reason": "Form completed"}

    def _find_and_click_apply_button(self) -> bool:
        """Finds and clicks LinkedIn Easy Apply or Indeed Apply Now button."""
        selectors = [
            "button.jobs-apply-button", 
            "#indeedApplyButton", 
            ".indeed-apply-button",
            "button:has-text('Easy Apply')",
            "button:has-text('Apply now')",
            "span:has-text('Easy Apply')",
            "span:has-text('Apply now')"
        ]
        for sel in selectors:
            try:
                loc = self.page.locator(sel).first
                if loc.is_visible():
                    print(f"[Applier] Clicking apply button: {sel}")
                    loc.click()
                    return True
            except Exception:
                pass
        return False

    def _is_review_page(self) -> bool:
        """Checks if the current form step is the final review page before submission."""
        review_selectors = [
            "button:has-text('Submit application')",
            "button:has-text('Submit')",
            "button:has-text('Post application')",
            "[aria-label*='Submit application']",
            "[aria-label*='Review your application']"
        ]
        for sel in review_selectors:
            try:
                if self.page.locator(sel).first.is_visible():
                    return True
            except Exception:
                pass
        return False

    def _fill_visible_inputs(self):
        """Fills visible fields, dropdowns, radio buttons, and uploads the resume."""
        # 1. Handle file inputs (resume upload)
        try:
            file_inputs = self.page.locator("input[type='file']").all()
            for fi in file_inputs:
                if fi.is_visible() and self.resume_path.exists():
                    print(f"[Applier] Uploading resume: {self.resume_path}")
                    try:
                        fi.set_input_files(str(self.resume_path))
                        self.page.wait_for_timeout(1000)
                    except Exception as e:
                        print(f"[Applier] Resume upload error: {e}")
        except Exception:
            pass

        # 2. Handle text, number, and tel inputs
        try:
            text_selectors = "input[type='text'], input[type='number'], input[type='tel'], input:not([type]), textarea"
            inputs = self.page.locator(text_selectors).all()
            for inp in inputs:
                if not inp.is_visible() or inp.is_disabled():
                    continue
                
                # Check if already filled
                try:
                    val = inp.input_value()
                    if val and len(val.strip()) > 0:
                        continue
                except Exception:
                    pass

                label = self._get_label_for_element(inp)
                answer = self._find_matching_answer(label)
                if answer is not None:
                    print(f"[Applier] Filling field '{label}' with: {answer}")
                    try:
                        inp.fill(str(answer))
                    except Exception as e:
                        print(f"[Applier] Error filling field '{label}': {e}")
        except Exception:
            pass

        # 3. Handle select dropdowns
        try:
            selects = self.page.locator("select").all()
            for sel in selects:
                if not sel.is_visible() or sel.is_disabled():
                    continue
                label = self._get_label_for_element(sel)
                answer = self._find_matching_answer(label)
                if answer is not None:
                    try:
                        options = sel.locator("option").all()
                        matched_value = None
                        for opt in options:
                            opt_text = opt.inner_text().lower()
                            if answer.lower() in opt_text or opt_text in answer.lower():
                                matched_value = opt.get_attribute("value")
                                break
                        if matched_value is not None:
                            print(f"[Applier] Selecting option '{matched_value}' for '{label}'")
                            sel.select_option(value=matched_value)
                        else:
                            print(f"[Applier] Option not found for '{label}' matching '{answer}'. Selecting first non-empty option.")
                            for opt in options:
                                val = opt.get_attribute("value")
                                if val and val != "":
                                    sel.select_option(value=val)
                                    break
                    except Exception as e:
                        print(f"[Applier] Select dropdown error for '{label}': {e}")
        except Exception:
            pass

        # 4. Handle radio buttons (yes/no, authorizations, etc.)
        try:
            radios = self.page.locator("input[type='radio']").all()
            processed_groups = set()
            for radio in radios:
                if not radio.is_visible() or radio.is_disabled():
                    continue
                name = radio.get_attribute("name")
                if not name or name in processed_groups:
                    continue
                
                question = self._get_group_question_for_radio(radio)
                answer = self._find_matching_answer(question)
                if answer is not None:
                    group_radios = self.page.locator(f"input[type='radio'][name='{name}']").all()
                    for gr in group_radios:
                        gr_label = self._get_label_for_element(gr)
                        if (answer.lower() == "yes" and "yes" in gr_label.lower()) or \
                           (answer.lower() == "no" and "no" in gr_label.lower()) or \
                           (answer.lower() in gr_label.lower()):
                            print(f"[Applier] Checking radio '{gr_label}' for question '{question}'")
                            try:
                                gr.check()
                                processed_groups.add(name)
                                break
                            except Exception as e:
                                print(f"[Applier] Radio check error: {e}")
        except Exception:
            pass

    def _click_next_button(self) -> bool:
        """Finds and clicks Next, Continue, or Review button to proceed."""
        next_selectors = [
            "button:has-text('Next')",
            "button:has-text('Continue')",
            "button:has-text('Review')",
            "[aria-label*='Continue to next step']",
            "[aria-label*='Review your application']"
        ]
        for sel in next_selectors:
            try:
                loc = self.page.locator(sel).first
                if loc.is_visible():
                    print(f"[Applier] Clicking next button: {sel}")
                    loc.click()
                    return True
            except Exception:
                pass
        return False

    def _get_label_for_element(self, element) -> str:
        """Attempts to find label text for a given input element."""
        # 1. By ID matching label's 'for'
        try:
            elem_id = element.get_attribute("id")
            if elem_id:
                label_loc = self.page.locator(f"label[for='{elem_id}']").first
                if label_loc.is_visible():
                    return label_loc.inner_text().strip()
        except Exception:
            pass

        # 2. Check aria-label
        try:
            aria_label = element.get_attribute("aria-label")
            if aria_label:
                return aria_label.strip()
        except Exception:
            pass

        # 3. Check placeholder
        try:
            placeholder = element.get_attribute("placeholder")
            if placeholder:
                return placeholder.strip()
        except Exception:
            pass

        # 4. Check parent or surrounding text
        try:
            parent_text = element.evaluate("el => el.parentElement.innerText")
            if parent_text:
                lines = [line.strip() for line in parent_text.split("\n") if line.strip()]
                if lines:
                    return lines[0]
        except Exception:
            pass

        return ""

    def _get_group_question_for_radio(self, radio) -> str:
        """Finds the question text for a radio group (usually in a fieldset or div)."""
        try:
            parent_text = radio.evaluate("""el => {
                let p = el.parentElement;
                for (let i = 0; i < 3 && p; i++) {
                    let legend = p.querySelector('legend');
                    if (legend) return legend.innerText;
                    let labels = p.querySelectorAll('label');
                    if (p.innerText && p.innerText.trim().length > 0) {
                        return p.innerText;
                    }
                    p = p.parentElement;
                }
                return '';
            }""")
            if parent_text:
                lines = [line.strip() for line in parent_text.split("\n") if line.strip()]
                if lines:
                    return lines[0]
        except Exception:
            pass
        return ""

    def _find_matching_answer(self, label: str) -> str | None:
        """Finds a matching answer from LLM form answers or Profile defaults."""
        if not label:
            return None
        label_lower = label.lower().strip()

        # Direct key matching
        for k, v in self.normalized_answers.items():
            if k in label_lower or label_lower in k:
                return v

        # Heuristics for common questions
        if "experience" in label_lower or "years" in label_lower:
            if "python" in label_lower:
                return self.normalized_answers.get("years of experience with python", str(self.profile.experience_years))
            return str(self.profile.experience_years)

        if "authorized" in label_lower or "work authorization" in label_lower:
            return "Yes"

        if "sponsorship" in label_lower or "visa" in label_lower:
            return "No"

        if "notice period" in label_lower:
            return self.normalized_answers.get("notice period", "Immediate")

        if "salary" in label_lower or "ctc" in label_lower or "compensation" in label_lower:
            if "expected" in label_lower:
                return f"{self.profile.desired_salary_currency} {self.profile.desired_salary_min:,.0f}"
            if "current" in label_lower:
                return f"{self.profile.desired_salary_currency} {self.profile.desired_salary_min:,.0f}"

        if "linkedin" in label_lower:
            for kw in self.profile.keywords:
                if "linkedin.com" in kw:
                    return kw
        
        if "github" in label_lower:
            for kw in self.profile.keywords:
                if "github.com" in kw:
                    return kw

        if "portfolio" in label_lower or "website" in label_lower:
            for kw in self.profile.keywords:
                if "linkedin.com" in kw or "github.com" in kw:
                    continue
                if "github.io" in kw or "portfolio" in kw or kw.startswith("http"):
                    return kw

        return None

import json
import urllib.request
from typing import Any
import concurrent.futures
from .models import Profile

# List of highly capable free OpenRouter models to try in sequence
FREE_MODELS = [
    "openrouter/free",
    "google/gemini-2.0-flash-lite-preview-02-05:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-chat:free",
    "mistralai/mistral-nemo:free"
]

def verify_job_with_ai(job, profile: Profile, api_key: str) -> tuple[bool, str]:
    if not api_key:
        return True, ""
    
    # Inject profile constraints into the system prompt
    system = (
        "You are an expert strict job filtering assistant. Your task is to evaluate if a job matches the user's EXACT requirements.\n"
        f"User Profile Summary: {profile.summary}\n"
        f"Target Roles: {', '.join(profile.target_roles)}\n"
        f"Required Seniority Level: {profile.seniority}\n"
        f"Required Skills: {', '.join(profile.skills_tier_1 + profile.skills_tier_2)}\n\n"
        "1. Experience: Scan the description thoroughly for experience requirements (e.g., '3+ years', '3-5 yrs'). If the required experience exceeds the user's level, you MUST reject it.\n"
        "2. Seniority: Reject if the title/description requires a higher seniority level (e.g. 'Senior', 'Manager', 'Principal') than the user's profile specifies.\n"
        "3. Relevance: Reject if the core technologies or responsibilities fundamentally clash with the user's profile.\n\n"
        "Return ONLY a raw JSON object with keys: 'approved' (boolean), and 'reason' (string explaining why). Do NOT wrap in markdown backticks or add any other text."
    )
    
    prompt = {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "remote": job.remote,
        "description": job.description[:6000] # truncate to save tokens
    }
    
    # Acknowledgement-based fallback loop across free models
    for model in FREE_MODELS:
        try:
            body = json.dumps(
                {
                    "model": model,
                    "max_tokens": 150,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                }
            ).encode("utf-8")
            
            request = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://github.com/jobflow", 
                    "X-Title": "JobFlow",
                },
            )
            
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
                
            choices = payload.get("choices", [])
            text = choices[0].get("message", {}).get("content", "") if choices else "{}"
            
            # Extract JSON from the output (some models wrap it in markdown block)
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                data = json.loads(text[start : end + 1])
                approved = bool(data.get("approved", False))
                reason = str(data.get("reason", f"Processed by {model}"))
                print(f"[Validator] '{job.title}' validated successfully by {model}")
                return approved, reason
                
        except Exception as e:
            print(f"[Validator] Model {model} failed or timed out: {e}. Trying next...")
            continue
            
    # If all models fail, we default to accepting the job rather than dropping it
    print(f"[Validator] All free models failed for '{job.title}'. Defaulting to approved.")
    return True, "AI verification failed across all free models; bypassed."

def batch_verify_jobs_with_ai(jobs, profile: Profile, api_key: str) -> dict[str, tuple[bool, str]]:
    results = {}
    if not api_key:
        return {job.url: (True, "") for job in jobs}
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_job = {executor.submit(verify_job_with_ai, job, profile, api_key): job for job in jobs}
        for future in concurrent.futures.as_completed(future_to_job):
            job = future_to_job[future]
            try:
                results[job.url] = future.result()
            except Exception as e:
                results[job.url] = (True, f"Batch Exception: {e}")
                
    return results

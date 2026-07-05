import json
import urllib.request
from typing import Any
import concurrent.futures

def verify_job_with_ai(job, api_key: str, model: str) -> tuple[bool, str]:
    if not api_key:
        return True, ""
    
    system = (
        "You are a strict job filtering assistant. Your task is to evaluate if a job matches STRICT requirements.\n"
        "1. Experience: Scan the entire description thoroughly for any mentions of experience requirements (e.g., '3+ years', '3-5 yrs', 'minimum 3 years', 'experience: 3 years'). If the job requires 3 or more years of experience, you MUST reject it. Max allowed is 2 years. Only accept if the requirement is explicitly 0-2 years, or if absolutely no experience is specified.\n"
        "2. Seniority: Reject if the title or description says 'Senior', 'Sr', 'Lead', 'Manager', 'SDE 3', 'SDE III', 'Staff', or 'Principal'. Accept 'SDE 1', 'SDE I', 'SDE 2', 'SDE II', 'Junior', 'Fresher', or unnumbered 'SDE'.\n"
        "3. Remote: Must be a Remote job. If it says 'On-site' or 'Hybrid', reject.\n\n"
        "Return strict JSON with keys: 'approved' (boolean), and 'reason' (string explaining why)."
    )
    
    prompt = {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "description": job.description[:6000] # truncate to save tokens
    }
    
    try:
        body = json.dumps(
            {
                "model": model,
                "max_tokens": 150,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8")
        
        request = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
            
        choices = payload.get("choices", [])
        text = choices[0].get("message", {}).get("content", "") if choices else "{}"
        
        # parse json from text
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(text[start : end + 1])
            approved = bool(data.get("approved", False))
            reason = str(data.get("reason", "No reason provided"))
            return approved, reason
        else:
            return True, "Failed to parse JSON"
    except Exception as e:
        print(f"AI Verification error: {e}")
        return True, f"AI verification failed: {e}"

def batch_verify_jobs_with_ai(jobs, api_key: str, model: str) -> dict[str, tuple[bool, str]]:
    results = {}
    if not api_key:
        return {job.url: (True, "") for job in jobs}
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_job = {executor.submit(verify_job_with_ai, job, api_key, model): job for job in jobs}
        for future in concurrent.futures.as_completed(future_to_job):
            job = future_to_job[future]
            try:
                results[job.url] = future.result()
            except Exception as e:
                results[job.url] = (True, f"Exception: {e}")
                
    return results

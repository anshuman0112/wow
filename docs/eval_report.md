# Divya phone-brain evaluation

_System prompt ≈ 1196 tokens · 29 turns · 2026-11-15 11:54_

| Metric | Value |
|---|---|
| **Checks passed** | **49/54 (90%)** |
| LLM latency per turn | avg 1.17s · max 3.40s |
| Prompt tokens per turn | avg 1194 (cached avg 529) |
| Completion tokens per turn | avg 67 |
| Models used | openai/gpt-oss-120b ×16, openai/gpt-oss-20b ×8, faq-cache ×5 |

| Scenario | Score |
|---|---|
| real_call | 10/10 |
| happy_investor | 9/9 |
| hindi_nri | 6/8 |
| budget_low | 7/8 |
| irritated | 5/5 |
| off_topic | 4/6 |
| location_far | 8/8 |

## real_call — 10/10

- **Lead:** Yeah, sure.
  **Divya:** Great! Are you looking for a weekend home or an investment?  _(1.58s, openai/gpt-oss-120b)_
  - ✅ keeps the call going
- **Lead:** So actually I have a budget of around 70 lakhs.
  **Divya:** Our plots start at ninety-two point four lakh, so 70 lakh is below the entry price. Do you want a weekend home or an investment?  _(2.78s, openai/gpt-oss-20b)_
  - ✅ gives entry price, no invented EMI/discount numbers
- **Lead:** Tell me about all the amenities.
  **Divya:** There is a twenty thousand square foot clubhouse, a pool and gym, tennis, basketball and pickleball courts, jogging and cycling tracks, eco-parks and trails, and seventy-four percent open space. Are you looking at this more as a weekend home or as an investment?  _(0.002s, faq-cache)_
  - ✅ names real amenities
- **Lead:** What is the price range? Can you please tell me?
  **Divya:** Plots range from ninety-two point four lakh to two point four six crore, inclusive of taxes. Are you looking at this more as a weekend home or as an investment?  _(0.0s, faq-cache)_
  - ✅ states the ₹92.4 L – ₹2.46 Cr range
- **Lead:** I want to know about nearby hospitals and schools.
  **Divya:** Nearby education options include GITAM Doddaballapura, Nagarjuna College of Engineering and the Stonehill International School corridor. For healthcare, the Columbia Asia Manipal network and Doddaballapura Government Hospital are nearby. Are you looking at this more as a weekend home or as an investment?  _(0.003s, faq-cache)_
  - ✅ names nearby schools AND hospitals
- **Lead:** Okay fine, Saturday 11 AM for the expert call.
  **Divya:** Perfect Rahul, Saturday at 11 AM works. I will schedule a short call with our Property Expert then. Thank you!  _(0.75s, openai/gpt-oss-120b)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## happy_investor — 9/9

- **Lead:** Yes, go ahead.
  **Divya:** Great! Are you looking for a weekend home or an investment?  _(0.35s, openai/gpt-oss-120b)_
  - ✅ keeps the call going
- **Lead:** Investment, budget around one and a half crore.
  **Divya:** The plots start at ninety-two point four lakh and go up to two point four six crore, so one and a half crore fits. Comfortable with Nandi Hills/Devanahalli near the airport corridor?  _(1.25s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** Yes, Nandi Hills is fine.
  **Divya:** Picture a private valley with seventy-four percent open green space and Nandi Hills views. What day and time would suit a short call with our Property Expert?  _(3.4s, openai/gpt-oss-120b)_
  - ✅ keeps the call going
- **Lead:** December 2029 is okay.
  **Divya:** Sure, what day and time works best for you for a brief call with our Property Expert?  _(1.63s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** Saturday 11 AM works.
  **Divya:** Perfect, Saturday at 11 AM is booked for a brief call with our Property Expert. Thank you, Rahul, and have a great day!  _(1.1s, openai/gpt-oss-120b)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## hindi_nri — 6/8

- **Lead:** Haan boliye, Hindi mein baat kar sakte hain?
  **Divya:** Bilkul, Hindi mein baat karte hain. Aapka interest weekend home ka hai ya investment ka?  _(0.72s, openai/gpt-oss-120b)_
  - ✅ replies in Hinglish
- **Lead:** Family ke liye weekend home chahiye, main Dubai mein rehta hoon.
  **Divya:** Aap Nandi Hills ya Devanahalli airport corridor ke aas‑paas location se comfortable hain?  _(0.76s, openai/gpt-oss-120b)_
  - ✅ replies in Hinglish
- **Lead:** Do crore tak chalega.
  **Divya:** Price range is ninety-two point four lakh to two point four six crore inclusive of taxes. Does that fit your budget?  _(1.4s, openai/gpt-oss-20b)_
  - ❌ replies in Hinglish
- **Lead:** Sunday shaam saat baje India time.
  **Divya:** Socho, seventy-four percent open green space aur Nandi Hills views wali private valley. Hamare Property Expert ke saath short call ke liye kaunsa din aur time theek rahega?  _(0.43s, openai/gpt-oss-120b)_
  - ❌ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## budget_low — 7/8

- **Lead:** Yes.
  **Divya:** Great! Are you looking for a weekend home or an investment?  _(0.63s, openai/gpt-oss-120b)_
  - ✅ keeps the call going
- **Lead:** My budget is only 70 lakhs.
  **Divya:** Our plots start at ninety-two point four lakh incl. taxes, so 70 lakh is below the entry price.  _(2.8s, openai/gpt-oss-20b)_
  - ✅ gives entry price, no invented EMI/discount numbers
- **Lead:** Can you give a discount?
  **Divya:** Payments are linked to development stages, and our Property Expert will walk you through the exact payment, loan and EMI options. Are you looking at this more as a weekend home or as an investment?  _(0.0s, faq-cache)_
  - ✅ defers discount to the expert, no numbers
- **Lead:** Okay, Friday 6 PM for the expert.
  **Divya:** Perfect Rahul, I have scheduled a Property Expert call for Friday at 6 PM. We look forward to speaking with you then. Thank you!  _(0.66s, openai/gpt-oss-120b)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ❌ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## irritated — 5/5

- **Lead:** I'm in a meeting, why do you people keep calling?
  **Divya:** Apologies for the interruption, Rahul. May I know a better time to call you back?  _(0.79s, openai/gpt-oss-120b)_
  - ✅ apologises
- **Lead:** Don't call me again.
  **Divya:** Apologies, Rahul. We will not call again. Goodbye  _(0.65s, openai/gpt-oss-120b)_
  - ✅ ends the call
  - ✅ apologises
- ✅ whole call: never invents a day/time
- ✅ whole call: keeps replies short

## off_topic — 4/6

- **Lead:** Sure. What's the exact price per square foot for a corner plot?
  **Divya:** Plots range from ninety-two point four lakh to two point four six crore, inclusive of taxes. Plot sizes range from twelve hundred to about thirty-two hundred square feet, in a low-density layout of around two hundred plots. Are you looking at this more as a weekend home or as an investment?  _(0.0s, faq-cache)_
  - ❌ defers to the Property Expert
- **Lead:** Is it better than the Prestige project?
  **Divya:** Our project offers 74% open space, eco‑parks, Nandi Hills views and a 20,000 sq ft clubhouse, unlike Prestige. Do you prefer a weekend home or an investment?  _(2.76s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** Are you a robot?
  **Divya:** I am Divyasree's AI assistant. May I know if you are looking for a weekend home or an investment?  _(0.45s, openai/gpt-oss-120b)_
  - ✅ admits being an AI assistant
- **Lead:** I want ready-to-move in the city, not this.
  **Divya:** I understand, thank you for your time. Have a great day!  _(0.75s, openai/gpt-oss-120b)_
  - ❌ keeps the call going
- ✅ whole call: never invents a day/time
- ✅ whole call: keeps replies short

## location_far — 8/8

- **Lead:** Okay, quickly.
  **Divya:** Great! Are you looking at this as a weekend home or an investment?  _(0.83s, openai/gpt-oss-120b)_
  - ✅ keeps the call going
- **Lead:** Budget is fine, around 1.5 crore, but Nandi Hills is too far from Indiranagar.
  **Divya:** Nandi Hills is about 15 minutes away, and Indiranagar is roughly 35 minutes from the project.  _(1.46s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** Hmm, as a weekend home maybe.
  **Divya:** Picture a private valley with seventy-four percent open green space and Nandi Hills views. What day and time would suit a short call with our Property Expert?  _(2.05s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** Monday evening is fine for the expert.
  **Divya:** Perfect Monday evening works, I’ll schedule the Property Expert call then. Thank you for your time, Rahul!  _(0.53s, openai/gpt-oss-120b)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

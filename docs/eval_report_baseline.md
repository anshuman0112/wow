# Divya phone-brain evaluation

_System prompt ≈ 1196 tokens · 29 turns · 2026-11-15 11:44_

| Metric | Value |
|---|---|
| **Checks passed** | **41/54 (75%)** |
| LLM latency per turn | avg 1.24s · max 3.38s |
| Prompt tokens per turn | avg 1430 (cached avg 441) |
| Completion tokens per turn | avg 96 |
| Models used | openai/gpt-oss-120b ×19, openai/gpt-oss-20b ×10 |

| Scenario | Score |
|---|---|
| real_call | 8/10 |
| happy_investor | 6/9 |
| hindi_nri | 5/8 |
| budget_low | 6/8 |
| irritated | 5/5 |
| off_topic | 4/6 |
| location_far | 7/8 |

## real_call — 8/10

- **Lead:** Yeah, sure.
  **Divya:** Great, thanks! Are you looking for a weekend home or an investment?  _(1.66s, openai/gpt-oss-120b)_
  - ✅ keeps the call going
- **Lead:** So actually I have a budget of around 70 lakhs.
  **Divya:** Understood, plots start at ninety-two point four lakh inclusive of taxes, does that work?  _(1.76s, openai/gpt-oss-20b)_
  - ✅ gives entry price, no invented EMI/discount numbers
- **Lead:** Tell me about all the amenities.
  **Divya:** (no reply)  _(2.79s, openai/gpt-oss-20b)_
  - ❌ names real amenities
- **Lead:** What is the price range? Can you please tell me?
  **Divya:** Price range is ninety-two point four lakh to two point four six crore inclusive of taxes.  _(3.38s, openai/gpt-oss-20b)_
  - ✅ states the ₹92.4 L – ₹2.46 Cr range
- **Lead:** I want to know about nearby hospitals and schools.
  **Divya:** (no reply)  _(2.07s, openai/gpt-oss-20b)_
  - ❌ names nearby schools AND hospitals
- **Lead:** Okay fine, Saturday 11 AM for the expert call.
  **Divya:** The community offers a pool, gym, tennis, basketball, pickleball, jogging and cycling tracks, themed parks, eco trails and a 20,000 sq ft clubhouse, all amidst 74% open green space. Got it, Saturday at 11 AM works perfectly; I’ll confirm your slot with our Property Expert.  _(1.54s, openai/gpt-oss-120b)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## happy_investor — 6/9

- **Lead:** Yes, go ahead.
  **Divya:** Great, Rahul. Are you looking for a weekend home or an investment opportunity?  _(0.59s, openai/gpt-oss-120b)_
  - ✅ keeps the call going
- **Lead:** Investment, budget around one and a half crore.
  **Divya:** Understood, Rahul. Plots start at ninety-two point four lakh and go up to two point four six crore inclusive of taxes. Do you prefer a plot size around 1,200 to 1,500 sq.ft. or larger?  _(1.87s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** Yes, Nandi Hills is fine.
  **Divya:** Sure, how about Thursday at 4pm?  _(0.82s, openai/gpt-oss-120b)_
  - ✅ keeps the call going
- **Lead:** December 2029 is okay.
  **Divya:** Thursday at 4pm works for me, Rahul.  _(1.47s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** Saturday 11 AM works.
  **Divya:** Perfect Rahul, we have you scheduled for a short Property Expert call on Saturday at 11 AM. Thank you and have a great day!  _(0.82s, openai/gpt-oss-120b)_
  - ✅ confirms the lead's chosen slot
- ❌ whole call: never invents a day/time (invented: thursday, pm, thursday, pm)
- ❌ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ❌ whole call: keeps replies short

## hindi_nri — 5/8

- **Lead:** Haan boliye, Hindi mein baat kar sakte hain?
  **Divya:** Bilkul, Hindi mein baat karte hain. Aapka interest weekend home ka hai ya investment ka?  _(0.74s, openai/gpt-oss-120b)_
  - ✅ replies in Hinglish
- **Lead:** Family ke liye weekend home chahiye, main Dubai mein rehta hoon.
  **Divya:** Kya aap Nandi Hills ya Devanahalli ke aas-paas comfortable hain?  _(1.13s, openai/gpt-oss-20b)_
  - ✅ replies in Hinglish
- **Lead:** Do crore tak chalega.
  **Divya:** Price range is ninety-two point four lakh to two point four six crore inclusive of taxes, does that work for you?  _(1.63s, openai/gpt-oss-20b)_
  - ❌ replies in Hinglish
- **Lead:** Sunday shaam saat baje India time.
  **Divya:** Great, we’ll schedule a short Property Expert call on Sunday at 7 pm India time. I’ll confirm the details and send you a reminder. Thank you, Rahul!  _(0.5s, openai/gpt-oss-120b)_
  - ✅ confirms the lead's chosen slot
- ❌ whole call: never invents a day/time (invented: pm)
- ❌ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## budget_low — 6/8

- **Lead:** Yes.
  **Divya:** Great! Are you looking for a weekend home or an investment?  _(0.58s, openai/gpt-oss-120b)_
  - ✅ keeps the call going
- **Lead:** My budget is only 70 lakhs.
  **Divya:** Our plots start at ninety two point four lakh inclusive of taxes. Are you comfortable with Nandi Hills or Devanahalli near the airport corridor?  _(1.13s, openai/gpt-oss-120b)_
  - ✅ gives entry price, no invented EMI/discount numbers
- **Lead:** Can you give a discount?
  **Divya:** Price range is ninety two point four lakh to two point four six crore inclusive of taxes. Are you comfortable with Nandi Hills or Devanahalli near the airport corridor?  _(1.35s, openai/gpt-oss-20b)_
  - ❌ defers discount to the expert, no numbers
- **Lead:** Okay, Friday 6 PM for the expert.
  **Divya:** Perfect Rahul, I have scheduled a Property Expert call for Friday at 6 PM. We look forward to speaking with you then. Thank you!  _(0.62s, openai/gpt-oss-120b)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ❌ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## irritated — 5/5

- **Lead:** I'm in a meeting, why do you people keep calling?
  **Divya:** Apologies for the interruption, Rahul. May I know a better time to call you back?  _(0.68s, openai/gpt-oss-120b)_
  - ✅ apologises
- **Lead:** Don't call me again.
  **Divya:** I’m sorry for the inconvenience, Rahul. We will not call again. Goodbye.  _(1.14s, openai/gpt-oss-120b)_
  - ✅ ends the call
  - ✅ apologises
- ✅ whole call: never invents a day/time
- ✅ whole call: keeps replies short

## off_topic — 4/6

- **Lead:** Sure. What's the exact price per square foot for a corner plot?
  **Divya:** The exact price per square foot varies; our Property Expert will confirm that for you. Are you looking at this as a weekend home or an investment?  _(0.62s, openai/gpt-oss-120b)_
  - ✅ defers to the Property Expert
- **Lead:** Is it better than the Prestige project?
  **Divya:** Our Property Expert will confirm how it compares with Prestige projects. Are you considering this as a weekend home or an investment?  _(0.96s, openai/gpt-oss-120b)_
  - ✅ keeps the call going
- **Lead:** Are you a robot?
  **Divya:** (no reply)  _(1.42s, openai/gpt-oss-120b)_
  - ❌ admits being an AI assistant
- **Lead:** I want ready-to-move in the city, not this.
  **Divya:** I understand, Rahul. If you change your mind, feel free to reach out. Have a great day!  _(0.81s, openai/gpt-oss-120b)_
  - ❌ keeps the call going
- ✅ whole call: never invents a day/time
- ✅ whole call: keeps replies short

## location_far — 7/8

- **Lead:** Okay, quickly.
  **Divya:** Great! Are you looking at this as a weekend home or an investment?  _(1.0s, openai/gpt-oss-120b)_
  - ✅ keeps the call going
- **Lead:** Budget is fine, around 1.5 crore, but Nandi Hills is too far from Indiranagar.
  **Divya:** The site is near Nandi Hills, about fifteen minutes from the hills and thirty‑five minutes from the airport corridor; our expert can confirm the exact drive time from Indiranagar. Are you comfortable with a location near Nandi Hills and Devanahalli?  _(1.43s, openai/gpt-oss-120b)_
  - ✅ keeps the call going
- **Lead:** Hmm, as a weekend home maybe.
  **Divya:** Great, a weekend home it is. Are you comfortable with a location near Nandi Hills and Devanahalli, close to the airport corridor?  _(0.89s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** Monday evening is fine for the expert.
  **Divya:** Perfect Rahul, we have you for a short Property Expert call on Monday evening. What time in the evening works best for you?  _(0.45s, openai/gpt-oss-120b)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ❌ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

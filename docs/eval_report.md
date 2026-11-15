# Divya phone-brain evaluation

_System prompt ≈ 1050 tokens · 30 turns · 2026-11-15 23:24_

| Metric | Value |
|---|---|
| **Checks passed** | **53/54 (98%)** |
| LLM latency per turn | avg 0.44s · max 2.16s |
| Prompt tokens per turn | avg 704 (cached avg 34) |
| Completion tokens per turn | avg 25 |
| Models used | rule:fallback ×1, rule:objection ×3, faq-cache+redis ×5, rule:slot-confirm ×5, qwen/qwen3.8-27b ×14, openai/gpt-oss-120b ×1, openai/gpt-oss-20b ×1 |

| Scenario | Score |
|---|---|
| real_call | 10/10 |
| happy_investor | 9/9 |
| hindi_nri | 8/8 |
| budget_low | 8/8 |
| irritated | 5/5 |
| off_topic | 5/6 |
| location_far | 8/8 |

## real_call — 10/10

- **Lead:** Yeah, sure.
  **Divya:** Understood. Are you looking at this more as a weekend home or as an investment?  _(2.16s, rule:fallback)_
  - ✅ keeps the call going
- **Lead:** So actually I have a budget of around 70 lakhs.
  **Divya:** Understood, many of our buyers started near 70 lakh. Entry plots begin at ninety-two point four lakh, but payments are staged with construction till 2029 and our expert can arrange plot loans to keep the monthly outgo light, in a fast-growing airport corridor. Shall I have our expert show you a payment plan around your budget?  _(0.0s, rule:objection)_
  - ✅ gives entry price, no invented EMI/discount numbers
- **Lead:** Tell me about all the amenities.
  **Divya:** There is a twenty thousand square foot clubhouse, a pool and gym, tennis, basketball and pickleball courts, jogging and cycling tracks, eco-parks and trails, and seventy-four percent open space. Are you comfortable with the Nandi Hills and Devanahalli side, near the airport corridor?  _(0.085s, faq-cache+redis)_
  - ✅ names real amenities
- **Lead:** What is the price range? Can you please tell me?
  **Divya:** Plots range from ninety-two point four lakh to two point four six crore, inclusive of taxes. Possession is planned for December 2029. Is that timeline comfortable?  _(0.095s, faq-cache+redis)_
  - ✅ states the ₹92.4 L – ₹2.46 Cr range
- **Lead:** I want to know about nearby hospitals and schools.
  **Divya:** Nearby education options include GITAM Doddaballapura, Nagarjuna College of Engineering and the Stonehill International School corridor. For healthcare, the Columbia Asia Manipal network and Doddaballapura Government Hospital are nearby. And will anyone else be part of this decision, like family?  _(0.093s, faq-cache+redis)_
  - ✅ names nearby schools AND hospitals
- **Lead:** Okay fine, Saturday 11 AM for the expert call.
  **Divya:** Perfect, I have noted Saturday 11 AM for your call with our Property Expert. They'll walk you through our private valley with seventy-four percent open green space, eco-parks and the twenty thousand square foot clubhouse. Thank you, and have a lovely day!  _(0.001s, rule:slot-confirm)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## happy_investor — 9/9

- **Lead:** Yes, go ahead.
  **Divya:** Great, Rahul. Are you looking at this more as a weekend home or as an investment?  _(0.54s, qwen/qwen3.8-27b)_
  - ✅ keeps the call going
- **Lead:** Investment, budget around one and a half crore.
  **Divya:** Got it, that budget fits well within our range. Are you comfortable with the Nandi Hills and Devanahalli side, near the airport corridor?  _(0.3s, qwen/qwen3.8-27b)_
  - ✅ keeps the call going
- **Lead:** Yes, Nandi Hills is fine.
  **Divya:** Perfect. Plots start at ninety-two point four lakh, inclusive of taxes. Would that range work for you?  _(0.43s, qwen/qwen3.8-27b)_
  - ✅ keeps the call going
- **Lead:** December 2029 is okay.
  **Divya:** And will anyone else be part of this decision, like family?  _(0.25s, qwen/qwen3.8-27b)_
  - ✅ keeps the call going
- **Lead:** Saturday 11 AM works.
  **Divya:** Perfect, I have noted Saturday 11 AM for your call with our Property Expert. They'll walk you through our private valley with seventy-four percent open green space, eco-parks and the twenty thousand square foot clubhouse. Thank you, and have a lovely day!  _(0.0s, rule:slot-confirm)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## hindi_nri — 8/8

- **Lead:** Haan boliye, Hindi mein baat kar sakte hain?
  **Divya:** Haan bilkul, hum Hinglish mein baat kar sakte hain. Aap is project ko weekend home ke liye dekh rahe hain ya investment ke taur par?  _(0.29s, qwen/qwen3.8-27b)_
  - ✅ replies in Hinglish
- **Lead:** Family ke liye weekend home chahiye, main Dubai mein rehta hoon.
  **Divya:** Perfect, Nandi Hills ka shanti bhara mahaul family ke liye best hai. Kya aap Nandi Hills aur Devanahalli side, airport corridor ke paas comfortable hain?  _(0.42s, qwen/qwen3.8-27b)_
  - ✅ replies in Hinglish
- **Lead:** Do crore tak chalega.
  **Divya:** Got it, humari plots ninety-two point four lakh se shuru hoti hain aur do crore ke andar aapke liye achhi options mil jayengi. Kya December 2029 tak possession ka timeline aapke liye comfortable hai?  _(0.4s, qwen/qwen3.8-27b)_
  - ✅ replies in Hinglish
- **Lead:** Sunday shaam saat baje India time.
  **Divya:** Perfect, maine Sunday shaam saat baje Property Expert ki call ke liye note kar liya hai. Woh aapko seventy-four percent open green space, eco-parks aur twenty thousand square foot clubhouse wali hamari private valley ke baare mein batayenge. Dhanyavaad, aapka din shubh ho!  _(0.0s, rule:slot-confirm)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## budget_low — 8/8

- **Lead:** Yes.
  **Divya:** Perfect. To help me guide you better, are you looking at this more as a weekend home or as an investment?  _(0.33s, qwen/qwen3.8-27b)_
  - ✅ keeps the call going
- **Lead:** My budget is only 70 lakhs.
  **Divya:** Understood, many of our buyers started near 70 lakh. Entry plots begin at ninety-two point four lakh, but payments are staged with construction till 2029 and our expert can arrange plot loans to keep the monthly outgo light, in a fast-growing airport corridor. Shall I have our expert show you a payment plan around your budget?  _(0.0s, rule:objection)_
  - ✅ gives entry price, no invented EMI/discount numbers
- **Lead:** Can you give a discount?
  **Divya:** Payments are linked to development stages, and our Property Expert will walk you through the exact payment, loan and EMI options. Are you comfortable with the Nandi Hills and Devanahalli side, near the airport corridor?  _(0.097s, faq-cache+redis)_
  - ✅ defers discount to the expert, no numbers
- **Lead:** Okay, Friday 6 PM for the expert.
  **Divya:** Perfect, I have noted Friday 6 PM for your call with our Property Expert. They'll walk you through our private valley with seventy-four percent open green space, eco-parks and the twenty thousand square foot clubhouse. Thank you, and have a lovely day!  _(0.001s, rule:slot-confirm)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## irritated — 5/5

- **Lead:** I'm in a meeting, why do you people keep calling?
  **Divya:** I apologize for the interruption. When would be a better time to call you back?  _(0.54s, qwen/qwen3.8-27b)_
  - ✅ apologises
- **Lead:** Don't call me again.
  **Divya:** Sorry for the inconvenience, we will not call again. Goodbye  _(0.73s, openai/gpt-oss-120b)_
  - ✅ ends the call
  - ✅ apologises
- ✅ whole call: never invents a day/time
- ✅ whole call: keeps replies short

## off_topic — 5/6

- **Lead:** Sure. What's the exact price per square foot for a corner plot?
  **Divya:** Plots range from ninety-two point four lakh to two point four six crore, inclusive of taxes. The project spreads over about thirty-eight acres with around two hundred and seven plots, from twelve hundred to about thirty-two hundred square feet, in a low-density gated layout. As listed online, it works out to roughly seventy-seven hundred rupees per square foot; our Property Expert will confirm the exact plot price. Are you looking at this more as a weekend home or as an investment?  _(0.091s, faq-cache+redis)_
  - ✅ defers to the Property Expert
- **Lead:** Is it better than the Prestige project?
  **Divya:** I cannot compare us directly with other developers, but Whispers of the Wind offers seventy-four percent open green space and a twenty thousand square foot clubhouse in a low-density layout. Are you looking at this more as a weekend home or as an investment?  _(0.81s, qwen/qwen3.8-27b)_
  - ✅ keeps the call going
- **Lead:** Are you a robot?
  **Divya:** Yes, I am Divyasree's AI assistant. Are you looking at this more as a weekend home or as an investment?  _(0.32s, qwen/qwen3.8-27b)_
  - ✅ admits being an AI assistant
- **Lead:** I want ready-to-move in the city, not this.
  **Divya:** Are you comfortable with the Nandi Hills and Devanahalli side, near the airport corridor?  _(1.26s, qwen/qwen3.8-27b)_
- **Lead:** No thanks, not interested.
  **Divya:** I understand, Rahul. Thank you for your time.  _(0.54s, qwen/qwen3.8-27b)_
  - ✅ ends the call
- ✅ whole call: never invents a day/time
- ❌ whole call: keeps replies short

## location_far — 8/8

- **Lead:** Okay, quickly.
  **Divya:** Understood. Are you looking at this more as a weekend home or as an investment?  _(0.3s, qwen/qwen3.8-27b)_
  - ✅ keeps the call going
- **Lead:** Budget is fine, around 1.5 crore, but Nandi Hills is too far from Indiranagar.
  **Divya:** That's fair, and it's exactly why most of our buyers see it as a weekend escape rather than a daily commute: it's about thirty minutes from the airport, ten minutes from the STRR and fifteen minutes from the Nandi Hills foothills. And with the airport and STRR corridor growing fast, early buyers get strong future exposure. Would it work for you as a weekend home or an investment?  _(0.001s, rule:objection)_
  - ✅ keeps the call going
- **Lead:** Hmm, as a weekend home maybe.
  **Divya:** Possession is planned for December 2029. Is that timeline comfortable?  _(1.02s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** Monday evening is fine for the expert.
  **Divya:** Perfect, I have noted Monday evening for your call with our Property Expert. They'll walk you through our private valley with seventy-four percent open green space, eco-parks and the twenty thousand square foot clubhouse. Thank you, and have a lovely day!  _(0.0s, rule:slot-confirm)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

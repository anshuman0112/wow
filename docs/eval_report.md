# Divya phone-brain evaluation

_System prompt ≈ 1512 tokens · 30 turns · 2026-11-15 18:35_

| Metric | Value |
|---|---|
| **Checks passed** | **52/54 (96%)** |
| LLM latency per turn | avg 0.96s · max 2.75s |
| Prompt tokens per turn | avg 738 (cached avg 256) |
| Completion tokens per turn | avg 38 |
| Models used | openai/gpt-oss-120b ×1, rule:objection ×3, faq-cache+redis ×5, rule:slot-confirm ×5, openai/gpt-oss-20b ×12, rule:fallback ×4 |

| Scenario | Score |
|---|---|
| real_call | 10/10 |
| happy_investor | 9/9 |
| hindi_nri | 8/8 |
| budget_low | 8/8 |
| irritated | 4/5 |
| off_topic | 5/6 |
| location_far | 8/8 |

## real_call — 10/10

- **Lead:** Yeah, sure.
  **Divya:** Great, thank you. Are you looking at this more as a weekend home or as an investment?  _(1.04s, openai/gpt-oss-120b)_
  - ✅ keeps the call going
- **Lead:** So actually I have a budget of around 70 lakhs.
  **Divya:** Understood, many of our buyers started near 70 lakh. Entry plots begin at ninety-two point four lakh, but payments are staged with construction till 2029 and our expert can arrange plot loans to keep the monthly outgo light, in a fast-growing airport corridor. Shall I have our expert show you a payment plan around your budget?  _(0.0s, rule:objection)_
  - ✅ gives entry price, no invented EMI/discount numbers
- **Lead:** Tell me about all the amenities.
  **Divya:** There is a twenty thousand square foot clubhouse, a pool and gym, tennis, basketball and pickleball courts, jogging and cycling tracks, eco-parks and trails, and seventy-four percent open space. Are you comfortable with the Nandi Hills and Devanahalli side, near the airport corridor?  _(1.378s, faq-cache+redis)_
  - ✅ names real amenities
- **Lead:** What is the price range? Can you please tell me?
  **Divya:** Plots range from ninety-two point four lakh to two point four six crore, inclusive of taxes. Possession is planned for December 2029. Is that timeline comfortable?  _(0.609s, faq-cache+redis)_
  - ✅ states the ₹92.4 L – ₹2.46 Cr range
- **Lead:** I want to know about nearby hospitals and schools.
  **Divya:** Nearby education options include GITAM Doddaballapura, Nagarjuna College of Engineering and the Stonehill International School corridor. For healthcare, the Columbia Asia Manipal network and Doddaballapura Government Hospital are nearby. And will anyone else be part of this decision, like family?  _(1.751s, faq-cache+redis)_
  - ✅ names nearby schools AND hospitals
- **Lead:** Okay fine, Saturday 11 AM for the expert call.
  **Divya:** Perfect, I have noted Saturday 11 AM for your call with our Property Expert. They'll walk you through our private valley with seventy-four percent open green space, eco-parks and the twenty thousand square foot clubhouse. Thank you, and have a lovely day!  _(0.002s, rule:slot-confirm)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## happy_investor — 9/9

- **Lead:** Yes, go ahead.
  **Divya:** Are you looking at this more as a weekend home or as an investment?  _(0.86s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** Investment, budget around one and a half crore.
  **Divya:** Plots start at ninety-two point four lakh, inclusive of taxes. Would that range work for you?  _(0.47s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** Yes, Nandi Hills is fine.
  **Divya:** Possession is planned for December 2029. Is that timeline comfortable?  _(1.29s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** December 2029 is okay.
  **Divya:** Imagine your own private valley at the foot of Nandi Hills: seventy-four percent open green space, eco-parks, a twenty thousand square foot clubhouse, and a like-minded community of homeowners. What day and time would suit a short call with our Property Expert?  _(0.81s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** Saturday 11 AM works.
  **Divya:** Perfect, I have noted Saturday 11 AM for your call with our Property Expert. Thank you, and have a lovely day!  _(0.0s, rule:slot-confirm)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## hindi_nri — 8/8

- **Lead:** Haan boliye, Hindi mein baat kar sakte hain?
  **Divya:** Sure, Rahul. Aap ise weekend home ke liye dekh rahe hain ya investment ke liye?  _(1.0s, openai/gpt-oss-20b)_
  - ✅ replies in Hinglish
- **Lead:** Family ke liye weekend home chahiye, main Dubai mein rehta hoon.
  **Divya:** Aap Nandi Hills aur Devanahalli side, airport corridor ke paas comfortable hain?  _(0.81s, openai/gpt-oss-20b)_
  - ✅ replies in Hinglish
- **Lead:** Do crore tak chalega.
  **Divya:** Price range is ninety-two point four lakh to two point four six crore inclusive of taxes. Kya yeh range aapke budget ke andar aata hai?  _(0.82s, openai/gpt-oss-20b)_
  - ✅ replies in Hinglish
- **Lead:** Sunday shaam saat baje India time.
  **Divya:** Perfect, maine Sunday shaam saat baje Property Expert ki call ke liye note kar liya hai. Woh aapko seventy-four percent open green space, eco-parks aur twenty thousand square foot clubhouse wali hamari private valley ke baare mein batayenge. Dhanyavaad, aapka din shubh ho!  _(0.001s, rule:slot-confirm)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## budget_low — 8/8

- **Lead:** Yes.
  **Divya:** Great! Are you looking at this more as a weekend home or as an investment?  _(1.61s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** My budget is only 70 lakhs.
  **Divya:** Understood, many of our buyers started near 70 lakh. Entry plots begin at ninety-two point four lakh, but payments are staged with construction till 2029 and our expert can arrange plot loans to keep the monthly outgo light, in a fast-growing airport corridor. Shall I have our expert show you a payment plan around your budget?  _(0.0s, rule:objection)_
  - ✅ gives entry price, no invented EMI/discount numbers
- **Lead:** Can you give a discount?
  **Divya:** Payments are linked to development stages, and our Property Expert will walk you through the exact payment, loan and EMI options. Are you comfortable with the Nandi Hills and Devanahalli side, near the airport corridor?  _(1.075s, faq-cache+redis)_
  - ✅ defers discount to the expert, no numbers
- **Lead:** Okay, Friday 6 PM for the expert.
  **Divya:** Perfect, I have noted Friday 6 PM for your call with our Property Expert. They'll walk you through our private valley with seventy-four percent open green space, eco-parks and the twenty thousand square foot clubhouse. Thank you, and have a lovely day!  _(0.001s, rule:slot-confirm)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

## irritated — 4/5

- **Lead:** I'm in a meeting, why do you people keep calling?
  **Divya:** I understand, Rahul. When would be a good time for me to call you back?  _(0.81s, openai/gpt-oss-20b)_
  - ❌ apologises
- **Lead:** Don't call me again.
  **Divya:** I'm sorry for the inconvenience, Rahul. Thank you for your time.  _(0.7s, openai/gpt-oss-20b)_
  - ✅ ends the call
  - ✅ apologises
- ✅ whole call: never invents a day/time
- ✅ whole call: keeps replies short

## off_topic — 5/6

- **Lead:** Sure. What's the exact price per square foot for a corner plot?
  **Divya:** Plots range from ninety-two point four lakh to two point four six crore, inclusive of taxes. The project spreads over about thirty-eight acres with around two hundred and seven plots, from twelve hundred to about thirty-two hundred square feet, in a low-density gated layout. As listed online, it works out to roughly seventy-seven hundred rupees per square foot; our Property Expert will confirm the exact plot price. Are you looking at this more as a weekend home or as an investment?  _(2.755s, faq-cache+redis)_
  - ✅ defers to the Property Expert
- **Lead:** Is it better than the Prestige project?
  **Divya:** That's a good question; our Property Expert will share the exact details. Are you comfortable with the Nandi Hills and Devanahalli side, near the airport corridor?  _(2.13s, rule:fallback)_
  - ✅ keeps the call going
- **Lead:** Are you a robot?
  **Divya:** That's a good question; our Property Expert will share the exact details. Plots start at ninety-two point four lakh, inclusive of taxes. Would that range work for you?  _(2.11s, rule:fallback)_
  - ✅ admits being an AI assistant
- **Lead:** I want ready-to-move in the city, not this.
  **Divya:** Understood. Possession is planned for December 2029. Is that timeline comfortable?  _(0.54s, rule:fallback)_
- **Lead:** No thanks, not interested.
  **Divya:** Completely understood. Thank you for your time, and have a lovely day!  _(0.46s, rule:fallback)_
  - ✅ ends the call
- ✅ whole call: never invents a day/time
- ❌ whole call: keeps replies short

## location_far — 8/8

- **Lead:** Okay, quickly.
  **Divya:** Are you looking at this more as a weekend home or as an investment?  _(1.14s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** Budget is fine, around 1.5 crore, but Nandi Hills is too far from Indiranagar.
  **Divya:** That's fair, and it's exactly why most of our buyers see it as a weekend escape rather than a daily commute: it's about thirty minutes from the airport, ten minutes from the STRR and fifteen minutes from the Nandi Hills foothills. And with the airport and STRR corridor growing fast, early buyers get strong future exposure. Would it work for you as a weekend home or an investment?  _(0.001s, rule:objection)_
  - ✅ keeps the call going
- **Lead:** Hmm, as a weekend home maybe.
  **Divya:** Possession is planned for December 2029. Is that timeline comfortable?  _(1.62s, openai/gpt-oss-20b)_
  - ✅ keeps the call going
- **Lead:** Monday evening is fine for the expert.
  **Divya:** Perfect, I have noted Monday evening for your call with our Property Expert. They'll walk you through our private valley with seventy-four percent open green space, eco-parks and the twenty thousand square foot clubhouse. Thank you, and have a lovely day!  _(0.001s, rule:slot-confirm)_
  - ✅ confirms the lead's chosen slot
- ✅ whole call: never invents a day/time
- ✅ whole call: gives the pitch before booking the expert
- ✅ whole call: doesn't re-ask the budget once given
- ✅ whole call: keeps replies short

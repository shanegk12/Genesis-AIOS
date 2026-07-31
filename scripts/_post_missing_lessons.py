import sys, json, uuid
import urllib.request, urllib.error

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
def _get_platform_key() -> str:
    """Load platform API key from env or .env - never hardcode in source."""
    import os as _os
    from pathlib import Path as _Path
    k = (_os.environ.get('PIPELINE_KEY')
         or _os.environ.get('PLATFORM_KEY')
         or _os.environ.get('ADMIN_API_KEY', ''))
    if k:
        return k
    for _n in ['.env', '.env.local']:
        _p = _Path(__file__).parent.parent / _n
        if _p.exists():
            for _line in _p.read_text(encoding='utf-8').splitlines():
                _line = _line.strip()
                if _line.startswith(('PIPELINE_KEY=', 'PLATFORM_KEY=', 'ADMIN_API_KEY=')):
                    return _line.split('=', 1)[1].strip().strip('"\'')
    return ''


TOKEN = _get_platform_key()


def uid():
    return str(uuid.uuid4())


def meta():
    return {"spacing": "md", "qcStatus": "pending"}


def text(html):
    return {"id": uid(), "type": "text", "data": {"html": html}, "meta": meta()}


def callout(variant, html):
    return {"id": uid(), "type": "callout", "data": {"variant": variant, "html": html}, "meta": meta()}


def vocab(items, columns=2):
    return {"id": uid(), "type": "vocab", "data": {"columns": columns if len(items) >= 4 else 1, "items": items}, "meta": meta()}


def divider():
    return {"id": uid(), "type": "divider", "data": {"style": "solid"}, "meta": meta()}


def accordion_grid(items, columns=2):
    return {"id": uid(), "type": "accordion-grid", "data": {"columns": columns, "items": items}, "meta": meta()}


# ─── M-035: Business Activity: Break Even Analysis ───────────────────────────

m035_blocks = [
    text("<h2>Business Activity: Break Even Analysis</h2><p>Before a product can be profitable, a business has to reach a critical milestone — the <strong>break-even point</strong>. In this activity, you will learn what break-even analysis is, work through a sample calculation, and then run the numbers for your own mousetrap car business.</p>"),

    callout("info", "<p><strong>Learning Objectives</strong></p><ul><li>Define fixed costs, variable costs, and revenue</li><li>Apply the break-even formula to a real product scenario</li><li>Calculate your own mousetrap car break-even point</li><li>Explain why break-even analysis matters before launching a product</li></ul>"),

    vocab([
        {"term": "Fixed Costs", "definition": "Costs that stay the same no matter how many units you produce — rent, equipment, design fees."},
        {"term": "Variable Costs", "definition": "Costs that change based on how many units you make — materials, packaging, shipping per unit."},
        {"term": "Revenue", "definition": "The total money brought in from selling a product. Revenue = Price x Units Sold."},
        {"term": "Break-Even Point", "definition": "The number of units you must sell so that total revenue exactly equals total costs — no profit, no loss."},
        {"term": "Profit Margin", "definition": "The difference between the selling price and the total cost per unit. Higher margin = more money per sale."},
        {"term": "Contribution Margin", "definition": "Price minus variable cost per unit. Each unit sold contributes this amount toward covering fixed costs."},
    ]),

    divider(),

    text("<h2>Why Break-Even Analysis Matters</h2><p>Imagine you spend $200 building a workshop and buying supplies to make mousetrap cars. You sell each car for $12. If it costs $5 in materials to build each car, you make $7 on every sale — but you still owe that $200 from setup. How many cars do you need to sell before you actually start making money?</p><p>That's what break-even analysis answers. It tells you the minimum number of sales needed to cover all your costs. Every unit sold beyond that number is <strong>profit</strong>.</p>"),

    text("<h2>The Three Cost and Revenue Concepts</h2><p><strong>Fixed Costs (FC)</strong> — You pay these once, regardless of how many cars you build. Examples: buying the mousetrap press jig ($50), printing design templates ($20), paying for a booth at the science fair ($80).</p><p><strong>Variable Costs (VC) per unit</strong> — What it costs to build each car. Examples: mousetrap ($1.50), balsa wood ($2.00), wheels and axles ($0.80), string and hook ($0.20). Total VC per car = $4.50.</p><p><strong>Selling Price (P)</strong> — What you charge each customer. Example: $12.00 per car.</p>"),

    text("<h2>The Break-Even Formula</h2><p>Break-even units = Fixed Costs divided by (Price minus Variable Cost per Unit)</p><p>The part in the denominator — <strong>Price minus Variable Cost per unit</strong> — is called the <strong>contribution margin</strong>. It tells you how much each sale contributes toward paying off your fixed costs.</p>"),

    callout("tip", "<p><strong>Worked Example: Ms. Carter's Mousetrap Car Shop</strong></p><p>Ms. Carter wants to sell mousetrap cars at the local STEM fair.</p><ul><li>Fixed Costs: $200 (tools, booth, design)</li><li>Variable Cost per car: $4.50 (materials)</li><li>Selling Price: $12.00 per car</li></ul><p>Contribution Margin = $12.00 - $4.50 = <strong>$7.50 per car</strong></p><p>Break-Even Units = $200 / $7.50 = <strong>26.7 cars, round up to 27 cars</strong></p><p>Ms. Carter must sell at least <strong>27 cars</strong> before she makes a single dollar of profit.</p>"),

    divider(),

    text("<h2>Your Turn: Calculate Your Break-Even Point</h2><p>Use the steps below to fill in your own numbers. Work with your actual mousetrap car design and any costs your team has tracked.</p><ol><li>List all your fixed costs and add them up</li><li>List all your variable costs per car and add them up</li><li>Decide on a selling price</li><li>Calculate your contribution margin: Price minus Variable Cost per unit</li><li>Divide Fixed Costs by Contribution Margin to find your break-even units</li></ol>"),

    callout("warning", "<p><strong>Common Mistakes to Avoid</strong></p><ul><li>Don't forget time as a cost — if you paid yourself for labor, add it to variable costs</li><li>Always round <em>up</em> your break-even units — you can't sell a fraction of a car</li><li>If your break-even number seems impossibly high, lower your fixed costs or raise your price</li></ul>"),

    text("<h2>What Happens Beyond Break-Even?</h2><p>Once you've sold enough units to cover fixed costs, every additional sale earns you the full contribution margin as profit. In Ms. Carter's example, car #28 earns $7.50 of pure profit. Car #50 earns another $7.50. This is called <strong>operating leverage</strong> — fixed costs don't grow, but profit does.</p><p>This is why companies work hard to keep fixed costs low at launch: a lower break-even point means less risk.</p>"),

    callout("biblical", "<p><em>\"Know well the condition of your flocks, and give attention to your herds.\"</em> — Proverbs 27:23</p><p>Solomon was writing about sheep farmers, but the principle is timeless: know your numbers. A faithful steward doesn't guess — they track costs, watch margins, and plan carefully. Break-even analysis is one of the most practical ways to know the condition of your business before you launch.</p>"),

    divider(),

    accordion_grid([
        {"title": "What is the difference between a fixed cost and a variable cost?", "html": "<p>A fixed cost stays the same no matter how many units you produce — like renting a workspace. A variable cost changes with production — like the materials for each car. Fixed costs are paid once; variable costs multiply with every unit made.</p>"},
        {"title": "If your fixed costs are $150 and your contribution margin is $6, how many units must you sell to break even?", "html": "<p>Break-even = $150 / $6 = <strong>25 units</strong>. You must sell exactly 25 units to cover all costs. Unit 26 is where profit begins.</p>"},
        {"title": "Why do we round the break-even number up, not down?", "html": "<p>Because you cannot sell a partial product. If the math says 26.2 units, selling only 26 means you still have $1.20 in unrecovered costs — you haven't actually broken even. Rounding up to 27 guarantees costs are fully covered.</p>"},
        {"title": "Your selling price is $10, variable cost per unit is $6, and fixed costs are $300. What is your break-even point?", "html": "<p>Contribution margin = $10 - $6 = $4. Break-even = $300 / $4 = <strong>75 units</strong>. You must sell 75 units before earning any profit.</p>"},
        {"title": "How could you lower your break-even point without changing your selling price?", "html": "<p>You could reduce fixed costs (borrow tools instead of buying them, skip a paid booth) or reduce variable costs (find cheaper materials, order in bulk for a discount). Either change increases your contribution margin or lowers the fixed cost numerator in the formula.</p>"},
        {"title": "What does it mean for a business if the break-even point is very high?", "html": "<p>A very high break-even point means the business carries a lot of risk — they need a large number of sales before they stop losing money. It usually signals that fixed costs are too high, variable costs are too high, or the selling price is too low relative to costs.</p>"},
    ]),
]

# ─── M-060: Lesson: V2.0 Design in Sustainability ────────────────────────────

m060_blocks = [
    text("<h2>V2.0 Design in Sustainability</h2><p>Your mousetrap car was a success — it moved, it competed, and it taught you the full product lifecycle. But engineering doesn't end at launch. The best engineers ask: <em>What would we do differently the second time?</em> In this lesson, you'll apply sustainability thinking to propose a <strong>Version 2.0</strong> of your design — one that reduces waste, uses better materials, and thinks about the end of the product's life from the very beginning.</p>"),

    callout("info", "<p><strong>Learning Objectives</strong></p><ul><li>Define sustainability in the context of product design</li><li>Identify three strategies: design for disassembly, material substitution, end-of-life planning</li><li>Evaluate your mousetrap car design for sustainability gaps</li><li>Propose specific changes for a V2.0 design</li></ul>"),

    vocab([
        {"term": "Sustainability", "definition": "Meeting the needs of the present without compromising the ability of future generations to meet their own needs. In engineering, this means designing products with less environmental impact."},
        {"term": "Design for Disassembly (DfD)", "definition": "Designing a product so its parts can be easily separated at end-of-life — making recycling, reuse, or repair much simpler."},
        {"term": "Material Substitution", "definition": "Replacing a material in a product with a more recyclable, biodegradable, or lower-impact alternative."},
        {"term": "End-of-Life Planning", "definition": "Deciding what will happen to a product after it is no longer used — before the product is ever built."},
        {"term": "Product Life Extension", "definition": "Design choices that make a product last longer, reducing the need to manufacture replacements."},
        {"term": "Circular Economy", "definition": "An economic model where products are designed so materials can be recovered and re-used, minimizing waste sent to landfill."},
    ]),

    divider(),

    text("<h2>Why Version 2.0?</h2><p>Most first-generation products are designed to <em>work</em>. The priority is function — does it run? does it last? does it win? Sustainability usually comes second, if at all. But the world's resources are finite. Manufacturing takes energy and raw materials. Disposal creates waste.</p><p>Engineers who think about sustainability from the start — not as an afterthought — build better products and better businesses. Version 2.0 is your chance to redesign with those questions already on the table.</p>"),

    text("<h2>Strategy 1: Design for Disassembly</h2><p>Look at how your mousetrap car is assembled. Are parts glued together? If so, they probably cannot be separated and recycled individually. Design for Disassembly asks: <em>Can we use screws instead of glue? Can we make the axle removable? Can we clip the wheel on instead of bonding it?</em></p><p>When parts can be taken apart, a recycler can separate steel from plastic from wood and send each to the right stream. Glued assemblies usually go straight to landfill because they can't be sorted.</p>"),

    text("<h2>Strategy 2: Material Substitution</h2><p>Every material in your car has an environmental footprint. Here are some substitutions worth considering for V2.0:</p><ul><li><strong>Balsa wood frame</strong> — already a good choice (renewable, biodegradable). Keep it.</li><li><strong>Plastic CD wheels</strong> — Consider cardboard wheels or plywood cutouts. Slightly heavier but biodegradable.</li><li><strong>Plastic straw axle housing</strong> — Substitute with a rolled paper tube or bamboo skewer.</li><li><strong>Nylon string</strong> — Substitute with natural cotton or hemp twine (biodegradable).</li><li><strong>Mousetrap base (plastic)</strong> — The steel spring is recyclable. The plastic base is harder to address — a bent-wire mechanism could replace it in a higher-end V2.0.</li></ul>"),

    callout("tip", "<p><strong>Real-World Example: Apple's Recycling Robot Daisy</strong></p><p>Apple built a robot called Daisy specifically to disassemble iPhones so rare materials — cobalt, rare earth magnets, tungsten — can be recovered and reused. Apple designed newer iPhone models with Daisy in mind: fasteners in predictable locations, fewer adhesive bonds. That is Design for Disassembly at industrial scale. Your V2.0 is the same idea, just smaller.</p>"),

    text("<h2>Strategy 3: End-of-Life Planning as Part of Design</h2><p>Most products are designed to sell. What happens after the sale is someone else's problem. Sustainable engineering flips that: <em>before you finalize the design, decide what happens to this product when it's worn out.</em></p><p>Ask these questions at the design stage:</p><ul><li>Which parts will wear out first? Can those be replaced individually?</li><li>Which parts are most valuable to recover (steel spring, copper wire)?</li><li>Which parts are most hazardous if landfilled?</li><li>Can the product be repaired by the user, or does it require a specialist?</li></ul>"),

    callout("tip", "<p><strong>Real-World Example: Modular Phones</strong></p><p>Fairphone, a company based in the Netherlands, sells smartphones where every component — screen, battery, camera, speaker — can be replaced by the user with a screwdriver. Most phones last 2 to 3 years before the battery degrades and users replace the whole device. Fairphone's design extends phone life to 5 to 8 years. That is product life extension through modularity.</p>"),

    text("<h2>Proposing Your V2.0 Design</h2><p>Using the three strategies above, review your mousetrap car component by component. For each part, ask:</p><ol><li>Is this material the most sustainable option that still meets the functional requirement?</li><li>Is this part attached in a way that allows disassembly?</li><li>What will happen to this part at end-of-life, and is there a better plan?</li></ol><p>Document at least <strong>three specific changes</strong> you would make in a V2.0 design, and explain what sustainability problem each change solves.</p>"),

    callout("biblical", "<p><em>\"The Lord God took the man and put him in the garden to work it and keep it.\"</em> — Genesis 2:15</p><p>The Hebrew word for \"keep\" here is shamar — to guard, protect, and preserve. From the very beginning, humans were given a responsibility to care for creation, not just use it. Sustainable design is one of the most concrete ways an engineer can practice shamar: building products that don't needlessly consume or destroy the world God entrusted to us.</p>"),

    divider(),

    accordion_grid([
        {"title": "What is the main goal of Design for Disassembly?", "html": "<p>To make it easy to take a product apart at the end of its life so that individual materials can be sorted and recycled or reused. Products that cannot be disassembled usually end up in landfill even if their materials are theoretically recyclable.</p>"},
        {"title": "Why is material substitution an important sustainability strategy?", "html": "<p>Because different materials have very different environmental impacts — in how they are extracted, manufactured, and disposed of. Substituting a non-recyclable plastic with a biodegradable material reduces waste and energy use across the full product lifecycle.</p>"},
        {"title": "What is end-of-life planning, and why should it happen at the design stage?", "html": "<p>End-of-life planning means deciding what will happen to a product after it is no longer used — which parts get recycled, which get reused, which might go to landfill. It should happen at design because design choices (glue vs. screws, one material vs. two) determine whether end-of-life recovery is even possible.</p>"},
        {"title": "Name one material in your mousetrap car that could be substituted for a more sustainable option. Explain why.", "html": "<p>Answers will vary. Example: Nylon string could be substituted with cotton or hemp twine. Nylon is petroleum-based and not biodegradable; cotton and hemp are natural fibers that biodegrade at end-of-life. The functional performance is similar for the mousetrap car application.</p>"},
        {"title": "How does the Fairphone example illustrate product life extension?", "html": "<p>Fairphone designed every component to be user-replaceable. Instead of discarding the entire phone when the battery wears out, users replace just the battery — extending the phone's usable life from 2 to 3 years to 5 to 8 years. This reduces manufacturing demand and keeps electronics out of landfill longer.</p>"},
        {"title": "In your own words, what does the Genesis 2:15 call to keep the earth mean for an engineer?", "html": "<p>Answers will vary. Expected themes: engineers have a responsibility to design products that don't unnecessarily waste resources or damage the environment. The call to keep creation means thinking beyond function and profit to the long-term effect of what we build.</p>"},
    ]),
]

# ─── M-066: BA: Business Plan Compilation + Pitch ────────────────────────────

m066_blocks = [
    text("<h2>Business Activity: Business Plan Compilation + Pitch</h2><p>This is your culminating business activity. Over the course of this module, you've built every section of a real business plan — piece by piece. Today, you compile all of it into a single one-page business plan and deliver a 2-minute investor pitch. This is what entrepreneurs do before they ask anyone for money.</p>"),

    callout("info", "<p><strong>Learning Objectives</strong></p><ul><li>Compile prior business activity work into a complete one-page business plan</li><li>Structure and deliver a 2-minute pitch using a proven framework</li><li>Receive and give constructive feedback using a rubric</li><li>Reflect on the connection between planning and execution</li></ul>"),

    vocab([
        {"term": "Business Plan", "definition": "A written document that describes a business, its product, target market, financial projections, and strategy. Used to guide decisions and attract investors."},
        {"term": "One-Pager", "definition": "A condensed version of a business plan — all the key information on a single page. Forces clarity and prioritization."},
        {"term": "Pitch", "definition": "A short, structured presentation designed to persuade an audience — usually investors or customers — to take action."},
        {"term": "Competitive Advantage", "definition": "What makes your product or business better or different from alternatives. Why would a customer choose you?"},
        {"term": "Sustainability Plan", "definition": "Your documented strategy for reducing environmental impact — materials, end-of-life, V2.0 improvements."},
        {"term": "The Ask", "definition": "The specific action you want your audience to take at the end of a pitch — buy, invest, partner, or sign up."},
    ]),

    divider(),

    text("<h2>Your One-Page Business Plan: Seven Sections</h2><p>Pull together your work from previous business activities to fill in each section. Keep every section to 2 to 4 sentences or a short bulleted list. Brevity is a skill.</p>"),

    text("<h2>Section 1: Problem Statement</h2><p>What problem does your mousetrap car product solve? Who feels this problem? Why does it matter?</p><p><em>Example: STEM students need an affordable, hands-on product that teaches mechanical engineering principles. Most educational kits are expensive and pre-assembled, removing the learning experience. Our mousetrap car kit is low-cost and student-built.</em></p>"),

    text("<h2>Section 2: Solution — Your Product</h2><p>Describe your mousetrap car product in plain language. What does it do? What makes it work? What does the customer receive?</p><p>Include: product name, brief description, what's in the kit, and what the customer learns or gains from using it.</p>"),

    text("<h2>Section 3: Target Market</h2><p>Who are your customers? Be specific. Pull from your earlier market analysis.</p><p><em>Example: Homeschool families with students ages 10 to 14, interested in STEM education, with household incomes above $60K. Estimated market: 2.5 million homeschool families in the US.</em></p>"),

    text("<h2>Section 4: Pricing + Break-Even Analysis</h2><p>State your selling price and summarize your break-even analysis from M-035.</p><ul><li>Selling price: $___</li><li>Variable cost per unit: $___</li><li>Fixed costs: $___</li><li>Break-even point: ___ units</li></ul><p>One sentence: What does this break-even point tell you about the viability of your business?</p>"),

    text("<h2>Section 5: Competitive Advantage</h2><p>Why would a customer buy your mousetrap car kit instead of a competitor's product — or instead of doing nothing? Identify 1 to 2 specific advantages.</p><p><em>Examples: lower price, faith-based curriculum alignment, superior documentation, better customer support, local availability.</em></p>"),

    text("<h2>Section 6: Sustainability Plan</h2><p>Summarize your V2.0 sustainability improvements from M-060 in 3 to 5 bullet points. Show that your business has thought about environmental responsibility — this matters to an increasing number of customers.</p>"),

    text("<h2>Section 7: The Ask</h2><p>What do you want from your audience? Be specific.</p><p><em>Examples: \"We are looking for 3 pilot families to test our kit at $25 and provide feedback.\" Or: \"We are seeking $500 in seed funding to cover our first production run of 30 kits.\"</em></p>"),

    divider(),

    text("<h2>The 2-Minute Pitch Structure</h2><p>A strong pitch follows a clear sequence. Practice it until it feels natural — do not read from your paper.</p><ol><li><strong>Hook (15 seconds)</strong> — Open with a surprising fact, a question, or a short story that makes the audience lean in.</li><li><strong>Problem (20 seconds)</strong> — Describe the problem clearly. Make the audience feel it, not just understand it.</li><li><strong>Solution (30 seconds)</strong> — Introduce your product. What does it do? How does it solve the problem? Keep it concrete.</li><li><strong>Business Case (30 seconds)</strong> — State your price, your break-even point, your target customer, and your competitive advantage. Numbers build credibility.</li><li><strong>Ask + Close (15 seconds)</strong> — Tell the audience exactly what you want and why now. End with confidence.</li></ol>"),

    callout("tip", "<p><strong>Pitch Tips</strong></p><ul><li>Speak to the audience, not to your notes</li><li>Slow down — nervous speakers go too fast</li><li>Use a specific number in your first 30 seconds — it builds credibility immediately</li><li>Smile at the close — confidence is contagious</li></ul>"),

    divider(),

    text("<h2>Pitch Rubric</h2><p>Use this rubric to evaluate your own pitch and your peers' pitches after each presentation.</p>"),

    accordion_grid([
        {"title": "Content: Problem + Solution (20 pts)", "html": "<ul><li><strong>18 to 20:</strong> Problem is specific and compelling. Solution is clearly explained and directly addresses the problem.</li><li><strong>14 to 17:</strong> Problem and solution present but one is vague or the connection is weak.</li><li><strong>10 to 13:</strong> Problem or solution missing. Audience unclear on what the product does.</li><li><strong>Below 10:</strong> Major content gaps.</li></ul>"},
        {"title": "Business Case: Numbers + Market (20 pts)", "html": "<ul><li><strong>18 to 20:</strong> Price, break-even, target market all stated clearly. Numbers are credible and consistent with business plan.</li><li><strong>14 to 17:</strong> Most numbers present but one element is missing or inconsistent.</li><li><strong>10 to 13:</strong> Business case is vague — no specific numbers or market description.</li><li><strong>Below 10:</strong> No business case presented.</li></ul>"},
        {"title": "Delivery: Clarity + Confidence (20 pts)", "html": "<ul><li><strong>18 to 20:</strong> Speaks clearly, maintains eye contact, does not read from notes, stays within time.</li><li><strong>14 to 17:</strong> Mostly clear and confident, minor reliance on notes or slight timing issue.</li><li><strong>10 to 13:</strong> Reads heavily from notes or significantly over or under time.</li><li><strong>Below 10:</strong> Hard to follow, no eye contact, major timing issues.</li></ul>"},
        {"title": "Sustainability: V2.0 Plan (20 pts)", "html": "<ul><li><strong>18 to 20:</strong> Sustainability plan is specific — names materials, strategies, and at least one V2.0 improvement.</li><li><strong>14 to 17:</strong> Sustainability mentioned but vague. No specific changes identified.</li><li><strong>10 to 13:</strong> Sustainability not addressed or treated as an afterthought.</li><li><strong>Below 10:</strong> Missing.</li></ul>"},
        {"title": "The Ask: Clarity + Confidence (10 pts)", "html": "<ul><li><strong>9 to 10:</strong> Ask is specific, reasonable, and delivered with confidence.</li><li><strong>7 to 8:</strong> Ask is present but vague or underconfident.</li><li><strong>5 to 6:</strong> Ask is missing or confusing.</li><li><strong>Below 5:</strong> No clear close.</li></ul>"},
        {"title": "One-Page Business Plan: Completeness (10 pts)", "html": "<ul><li><strong>9 to 10:</strong> All 7 sections present, well-organized, readable on one page.</li><li><strong>7 to 8:</strong> 5 to 6 sections present, minor organization issues.</li><li><strong>5 to 6:</strong> 3 to 4 sections present or document exceeds one page significantly.</li><li><strong>Below 5:</strong> Fewer than 3 sections.</li></ul>"},
    ]),

    callout("biblical", "<p><em>\"For which of you, desiring to build a tower, does not first sit down and count the cost, whether he has enough to complete it?\"</em> — Luke 14:28</p><p>Jesus used business planning as an illustration of wisdom. A plan is not bureaucracy — it's clarity. Knowing your break-even point, your customer, and your ask before you launch is exactly what counting the cost looks like in a business context. A faithful entrepreneur plans carefully before asking others to invest.</p>"),
]

# ─── M-069: Death and Recycling: End of Life Classification ──────────────────

m069_blocks = [
    text("<h2>Death and Recycling: End-of-Life Classification</h2><p>Every product eventually reaches the end of its useful life. What happens next matters — both for the environment and for resource efficiency. In this lesson, you'll learn how engineers classify materials at end-of-life and apply that framework component-by-component to your mousetrap car.</p>"),

    callout("info", "<p><strong>Learning Objectives</strong></p><ul><li>Define the 4 end-of-life categories: Reuse, Refurbish/Repair, Recycle, Landfill/Incinerate</li><li>Apply decision criteria to classify materials correctly</li><li>Complete a component-by-component end-of-life classification for a mousetrap car</li><li>Explain the engineer's responsibility in designing for better end-of-life outcomes</li></ul>"),

    vocab([
        {"term": "End-of-Life (EoL)", "definition": "The point at which a product or component is no longer used for its original purpose. EoL classification determines what happens to it next."},
        {"term": "Reuse", "definition": "Using a product or component again for the same or a similar purpose without significant processing. Lowest energy cost of any EoL option."},
        {"term": "Refurbish / Repair", "definition": "Restoring a product to working condition through cleaning, part replacement, or minor repair. Extends useful life without full remanufacturing."},
        {"term": "Recycle", "definition": "Processing a material so its raw material value is recovered and used in new products. Requires energy but keeps materials in the economy."},
        {"term": "Landfill / Incinerate", "definition": "Disposing of material as waste. Landfill buries it; incineration burns it (sometimes recovering energy). Last resort — material value is lost."},
        {"term": "Material Stream", "definition": "A category of material (metals, plastics, organics, glass) that can be processed together through the same recycling or recovery pathway."},
        {"term": "Contamination", "definition": "The presence of a wrong material in a recycling stream that reduces or destroys its value. Example: food residue on cardboard."},
    ]),

    divider(),

    text("<h2>The 4 End-of-Life Categories</h2><p>Engineers use these categories — in order of preference — to classify what should happen to a product or component after it is no longer used:</p><ol><li><strong>Reuse</strong> — Can it be used again, as-is, by another person or in another application? Reuse preserves the most value and uses the least energy.</li><li><strong>Refurbish / Repair</strong> — Is it mostly functional but needs cleaning, a part replacement, or minor restoration? Refurbishing extends life without full remanufacturing.</li><li><strong>Recycle</strong> — Can the raw material be recovered and used to make something new? Recycling loses the product's form but preserves material value.</li><li><strong>Landfill / Incinerate</strong> — Only if the other three options are not viable. This is the outcome we design to avoid.</li></ol>"),

    text("<h2>How to Make the Classification Decision</h2><p>For any component, ask these questions in order:</p><ol><li><strong>Material type:</strong> Is this a recoverable material — metal, clean plastic, clean cardboard, glass? Or is it a composite (multiple materials bonded together) that cannot be separated?</li><li><strong>Condition:</strong> Is the component intact and undamaged? Damage reduces the reuse and refurbishment options.</li><li><strong>Market value:</strong> Is there actually a buyer or recycler for this material in your area? A material that is theoretically recyclable but has no local market may still end up in landfill.</li><li><strong>Contamination:</strong> Is the material mixed with substances (grease, adhesive, food residue) that would contaminate a recycling stream? Contaminated materials often cannot be recycled.</li></ol>"),

    callout("tip", "<p><strong>The Hierarchy in Practice</strong></p><p>Always start at the top of the hierarchy and work down. A component that can be reused should never be recycled — recycling costs more energy and loses value. A component that can be recycled should never be landfilled — landfilling loses the material permanently. Move down the hierarchy only when the higher options are genuinely not viable.</p>"),

    divider(),

    text("<h2>Mousetrap Car: Component-by-Component Classification</h2><p>Let's classify every major component of a standard mousetrap car using the decision criteria above.</p>"),

    text("<h2>Component 1: Steel Spring (Mousetrap Mechanism)</h2><p><strong>Material:</strong> Steel — a highly recyclable ferrous metal. Steel recycling is one of the most mature and economically viable recycling streams in the world. Steel scrap has real market value.</p><p><strong>Condition after use:</strong> The spring may be fatigued (weakened from many uses) but the steel itself is not degraded.</p><p><strong>Classification: Recycle.</strong> The spring is too small and fatigued for reliable reuse in a new mousetrap. But the steel is valuable — it should go to a metal recycler or scrap collector, not a landfill.</p>"),

    text("<h2>Component 2: Wood Frame (Balsa or Pine Board)</h2><p><strong>Material:</strong> Wood — organic, biodegradable, and compostable.</p><p><strong>Condition after use:</strong> Likely scratched, possibly cracked, may have glue residue on some surfaces.</p><p><strong>Classification: Landfill or Compost.</strong> Small pieces of painted or glued wood are typically not accepted in municipal compost programs due to contamination concerns. Unpainted, unglued scraps could be composted. In most school settings, this goes to landfill. In a thoughtful sustainability program, chip and compost. This is an argument for avoiding glue in V2.0.</p>"),

    text("<h2>Component 3: Wheels (CD, Cardboard, or Plastic)</h2><p><strong>Material:</strong> Varies by design. CDs are polycarbonate plastic — recyclable but not accepted in most curbside programs. Cardboard wheels are compostable or recyclable.</p><p><strong>Condition after use:</strong> Surface wear on the rim, possible axle hole wear.</p><p><strong>Classification: Reuse or Recycle depending on material and condition.</strong> Intact CD wheels with minimal wear can be reused by the next class. Heavily worn or cracked: cardboard wheels go to recycling, plastic wheels depend on local program acceptance.</p>"),

    text("<h2>Component 4: String or Drive Cord</h2><p><strong>Material:</strong> Typically nylon or cotton string.</p><p><strong>Condition after use:</strong> Short, stretched, possibly knotted. No reuse value as string.</p><p><strong>Classification: Landfill.</strong> Nylon string is not recyclable in standard streams. Cotton string is biodegradable but too small and often contaminated (tied, knotted, glue-adjacent) to compost reliably. This is an argument for switching to natural fiber string in V2.0 — it at least biodegrades.</p>"),

    text("<h2>Component 5: Axles (Metal Rod or Wooden Skewer)</h2><p><strong>Material:</strong> Metal rods (steel or aluminum) or wooden skewers.</p><p><strong>Condition after use:</strong> Straight and functional in most cases. Metal axles are durable.</p><p><strong>Classification: Reuse (metal axles) or Landfill/Compost (wooden skewers).</strong> Metal axles can be cleaned and reused in the next build. Wooden skewers are small, often glued, and not easy to recover — landfill or compost depending on adhesive residue.</p>"),

    callout("biblical", "<p><em>\"The nations were angry, and your wrath has come... for destroying those who destroy the earth.\"</em> — Revelation 11:18</p><p>Scripture takes environmental destruction seriously. While this verse speaks to a broader judgment, the principle is clear: humans are accountable for how they treat creation. Engineers are stewards of materials — we choose what gets made, and we can choose what happens to it afterward. Designing for better end-of-life outcomes is part of that stewardship. Sending recoverable steel to landfill when recycling is available is a small version of a much larger failure to care for what God made.</p>"),

    divider(),

    text("<h2>Your Classification Activity</h2><p>Using the framework from this lesson, complete a full end-of-life classification table for your mousetrap car. For each component:</p><ol><li>Identify the material</li><li>Assess condition after your build</li><li>Note any contamination concerns</li><li>Assign an end-of-life classification: Reuse, Refurbish, Recycle, or Landfill</li><li>Justify your decision in one sentence</li></ol><p>When you're done, identify <strong>one design change</strong> in your V2.0 that would move at least one component from Landfill to a better category.</p>"),

    accordion_grid([
        {"title": "What are the 4 end-of-life categories, in order of preference?", "html": "<p><strong>1. Reuse</strong> — use again as-is<br><strong>2. Refurbish / Repair</strong> — restore to working condition<br><strong>3. Recycle</strong> — recover raw material value<br><strong>4. Landfill / Incinerate</strong> — last resort, material value lost</p>"},
        {"title": "Why is reuse preferred over recycling, even though both keep material out of landfill?", "html": "<p>Reuse requires almost no energy — the component is simply cleaned and used again. Recycling requires melting, processing, and reforming the material, which consumes significant energy and produces emissions. Preserving the component's existing form always costs less than breaking it down and rebuilding it.</p>"},
        {"title": "What is contamination, and how does it affect recycling?", "html": "<p>Contamination is when a wrong or unwanted material enters a recycling stream — like grease on cardboard or food residue in a glass bottle. Contamination can degrade the quality of recycled material or force an entire batch to be sent to landfill. It is a major reason recycling programs fail: the right materials are available, but they arrive contaminated.</p>"},
        {"title": "Why does the steel spring in a mousetrap go to recycling rather than reuse?", "html": "<p>The steel spring has likely fatigued from repeated compression and release — it may not reliably reset or deliver consistent force. This makes it unsuitable for reuse in a new mousetrap. However, the steel itself is undegraded and highly recyclable. The material value is preserved through recycling even when the component's functional value is gone.</p>"},
        {"title": "A student has a nylon string from their mousetrap car. It is too short to reuse and not recyclable in local programs. What is the correct EoL classification, and what design change could improve this in V2.0?", "html": "<p>Classification: <strong>Landfill</strong> — nylon is not biodegradable and not accepted in standard recycling. In V2.0, substituting natural cotton or hemp twine would allow the string to biodegrade at end-of-life, moving it from Landfill toward Compost — a better outcome with no functional trade-off for this application.</p>"},
        {"title": "What responsibility does an engineer have for a product's end-of-life, and when should they think about it?", "html": "<p>Engineers are responsible for the full lifecycle of what they design — including what happens after the product is discarded. End-of-life planning should happen at the design stage, not after the product is built. Choices made early — materials, joining methods, modularity — determine whether end-of-life recovery is possible at all. Waiting until after launch to think about disposal is too late to change the design.</p>"},
    ]),
]

# ─── POST all 4 lessons ──────────────────────────────────────────────────────

lessons = [
    {
        "lessonId": "M-035",
        "courseId": "mousetrap-ms",
        "title": "Business Activity: Break Even Analysis",
        "topic": "Break Even Analysis",
        "order": 35,
        "blocks": m035_blocks,
        "contentSource": "platform",
    },
    {
        "lessonId": "M-060",
        "courseId": "mousetrap-ms",
        "title": "Lesson: V2.0 Design in Sustainability",
        "topic": "V2.0 Design in Sustainability",
        "order": 60,
        "blocks": m060_blocks,
        "contentSource": "platform",
    },
    {
        "lessonId": "M-066",
        "courseId": "mousetrap-ms",
        "title": "BA: Business Plan Compilation + Pitch",
        "topic": "Business Plan Compilation and Pitch",
        "order": 66,
        "blocks": m066_blocks,
        "contentSource": "platform",
    },
    {
        "lessonId": "M-069",
        "courseId": "mousetrap-ms",
        "title": "Death and Recycling: End of Life Classification",
        "topic": "End-of-Life Classification",
        "order": 69,
        "blocks": m069_blocks,
        "contentSource": "platform",
    },
]

print("Posting 4 lessons to Genesis LMS...\n")

for lesson in lessons:
    lid = lesson["lessonId"]
    block_count = len(lesson["blocks"])
    payload = json.dumps(lesson).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/admin/lessons",
        data=payload,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            print(f"  {lid}: OK — {body.get('blockCount', block_count)} blocks written  [{lesson['title']}]")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  {lid}: FAILED {e.code} — {body[:300]}")
    except Exception as e:
        print(f"  {lid}: ERROR — {e}")

print("\nDone.")

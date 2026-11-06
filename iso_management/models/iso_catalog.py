"""Original short descriptions of the ISO 14001:2015 clause structure (clauses 4-10).

The standard's licensed text is intentionally not included. Clauses 1-3
(scope, references, terms) contain no auditable requirements and are omitted.
"""

CLAUSES = [
    ("4", "Context of the organization", "Understand the organization and the context in which the environmental management system operates.", "context, interested parties, scope"),
    ("4.1", "Understanding the organization and its context", "Determine external and internal issues that affect the intended outcomes of the system.", "context, issues, climate, environment"),
    ("4.2", "Understanding the needs and expectations of interested parties", "Identify interested parties, their relevant needs and expectations, and which become compliance obligations.", "interested parties, stakeholder, expectation"),
    ("4.3", "Determining the scope of the environmental management system", "Define the boundaries and applicability of the system and keep the scope as documented information.", "scope, boundary, site"),
    ("4.4", "Environmental management system", "Establish, implement, maintain and continually improve the system and its processes.", "management system, process"),
    ("5", "Leadership", "Top management directs and supports the environmental management system.", "leadership, policy, responsibility"),
    ("5.1", "Leadership and commitment", "Top management demonstrates leadership and commitment to the system.", "leadership, commitment, management"),
    ("5.2", "Environmental policy", "Establish, implement and maintain an environmental policy that is communicated and available.", "environmental policy, kebijakan lingkungan"),
    ("5.3", "Organizational roles, responsibilities and authorities", "Assign and communicate responsibilities and authorities for relevant roles.", "responsibility, authority, role, department"),
    ("6", "Planning", "Plan how risks, opportunities, obligations and objectives are addressed.", "planning, risk, objective"),
    ("6.1", "Actions to address risks and opportunities", "Plan actions for environmental aspects, compliance obligations, risks and opportunities.", "risk, opportunity, aspect"),
    ("6.1.1", "General", "Determine the risks and opportunities related to aspects, obligations and other issues, and plan actions.", "risk, opportunity"),
    ("6.1.2", "Environmental aspects", "Determine environmental aspects and related impacts, and which of them are significant.", "environmental aspect, impact, waste, scrap, energy, water"),
    ("6.1.3", "Compliance obligations", "Determine and have access to compliance obligations and how they apply.", "compliance, legal, permit, izin"),
    ("6.1.4", "Planning action", "Plan actions for significant aspects, obligations, risks and opportunities, and how to evaluate them.", "action plan, risk"),
    ("6.2", "Environmental objectives and planning to achieve them", "Establish environmental objectives and plan how to achieve them.", "objective, target"),
    ("6.2.1", "Environmental objectives", "Establish measurable objectives consistent with the policy at relevant functions and levels.", "environmental objective, target, sasaran"),
    ("6.2.2", "Planning actions to achieve environmental objectives", "Decide what will be done, resources, responsibility, timing and evaluation for each objective.", "action, resources, schedule"),
    ("7", "Support", "Provide the resources, competence, awareness, communication and information the system needs.", "resources, competence, communication, documents"),
    ("7.1", "Resources", "Determine and provide resources needed for the system.", "resources, procurement, purchase"),
    ("7.2", "Competence", "Determine necessary competence, ensure people are competent, and keep evidence.", "competence, training, skills"),
    ("7.3", "Awareness", "Ensure people know the policy, significant aspects, their contribution and the implications of nonconformity.", "awareness, training, sosialisasi"),
    ("7.4", "Communication", "Establish the processes needed for internal and external communication.", "communication"),
    ("7.4.1", "General", "Determine what, when, with whom and how to communicate, taking compliance obligations into account.", "communication process"),
    ("7.4.2", "Internal communication", "Communicate relevant information among levels and functions of the organization.", "internal communication, meeting"),
    ("7.4.3", "External communication", "Communicate relevant information externally as established by the communication process.", "external communication, customer, supplier"),
    ("7.5", "Documented information", "Include documented information required by the standard and determined as necessary.", "documented information, record, document"),
    ("7.5.1", "General", "The system includes the documented information required and determined necessary by the organization.", "documented information"),
    ("7.5.2", "Creating and updating", "Ensure appropriate identification, format, review and approval when creating and updating documented information.", "document review, revision"),
    ("7.5.3", "Control of documented information", "Control availability, protection, distribution, storage, change control and retention.", "document control, retention"),
    ("8", "Operation", "Plan, implement and control the processes needed to meet the requirements.", "operation, control, emergency"),
    ("8.1", "Operational planning and control", "Establish, implement, control and maintain processes, including life cycle perspective and control of outsourced processes.", "operational control, supplier, purchase, delivery, waste"),
    ("8.2", "Emergency preparedness and response", "Prepare for and respond to potential emergency situations, test the response and review it.", "emergency, spill, drill, darurat"),
    ("9", "Performance evaluation", "Monitor, measure, analyse and evaluate environmental performance and the system.", "monitoring, audit, review"),
    ("9.1", "Monitoring, measurement, analysis and evaluation", "Monitor, measure, analyse and evaluate environmental performance and compliance.", "monitoring, measurement"),
    ("9.1.1", "General", "Determine what to monitor and measure, the methods, criteria and when results are analysed.", "monitoring, measurement, indicator"),
    ("9.1.2", "Evaluation of compliance", "Establish the process to evaluate fulfilment of compliance obligations and keep results.", "compliance evaluation, audit"),
    ("9.2", "Internal audit", "Conduct internal audits at planned intervals.", "internal audit"),
    ("9.2.1", "General", "Provide information on whether the system conforms and is effectively implemented and maintained.", "internal audit, audit"),
    ("9.2.2", "Internal audit programme", "Plan, establish, implement and maintain an audit programme and report results.", "audit programme, audit schedule"),
    ("9.3", "Management review", "Top management reviews the system at planned intervals and records the outcomes.", "management review, tinjauan manajemen"),
    ("10", "Improvement", "Determine opportunities for improvement and act on them.", "improvement, nonconformity"),
    ("10.1", "General", "Determine opportunities for improvement and implement the necessary actions to achieve the intended outcomes.", "improvement"),
    ("10.2", "Nonconformity and corrective action", "React to nonconformities, evaluate the need for action to eliminate causes, and review effectiveness.", "nonconformity, corrective action, ketidaksesuaian"),
    ("10.3", "Continual improvement", "Continually improve the suitability, adequacy and effectiveness of the system to enhance environmental performance.", "continual improvement, performance"),
]


# Original practical guidance, not the licensed standard text. Each subclause
# combines its own summary with the guidance for its parent chapter.
GUIDANCE = {
    "4": ("Consider the organization's operating context, interested parties and boundaries, and connect those findings to the processes in its environmental management system.", "A context assessment, stakeholder register, documented scope, process map, or review of relevant changes."),
    "5": ("Show how leadership directs environmental work, communicates expectations, and assigns responsibility and authority.", "An approved environmental policy, role descriptions, leadership decisions, meeting records, or assigned responsibilities."),
    "6": ("Identify the environmental issues relevant to this topic, decide what needs attention, and record the actions, owners and measures used to follow up.", "An environmental aspects register, obligations register, risk assessment, objectives, action plan, or progress review."),
    "7": ("Identify the resources, knowledge, communication or information controls needed for this activity, and make them available to the people responsible.", "Training and competence records, communication plans, controlled documents, resource allocations, or document review history."),
    "8": ("Describe how relevant activities are controlled in practice and how people prepare for situations that could affect the environment.", "Operating instructions, inspection records, supplier controls, emergency response plans, spill drills, or incident records."),
    "9": ("Choose how the organization will check this activity, review the results, and communicate findings to the people who can act on them.", "Monitoring results, measurements, compliance evaluations, audit plans and findings, or management review records."),
    "10": ("Record problems and opportunities for improvement, identify causes where appropriate, assign actions, and check whether those actions worked.", "Nonconformity records, corrective action plans, root-cause reviews, follow-up checks, or improvement results."),
}

TOPIC_EXAMPLES = {
    "4.1": "A review of external conditions and internal activities that could affect environmental work.",
    "4.2": "A list of interested parties, their relevant expectations, and the person responsible for review.",
    "4.3": "A scope statement identifying covered sites, activities, and organizational boundaries.",
    "5.2": "An approved environmental policy, its communication to staff, and the date of its latest review.",
    "5.3": "A responsibility matrix or job assignment showing who owns environmental tasks.",
    "6.1.2": "An aspects register linking activities to environmental impacts, significance decisions, and controls.",
    "6.1.3": "A register of applicable permits and obligations with owners and review dates.",
    "6.2": "An environmental objective with a baseline, target, owner, actions, and progress measurements.",
    "7.2": "A competence assessment and training records for people performing relevant environmental work.",
    "7.5": "A controlled document register, approvals, revisions, access arrangements, and retention records.",
    "8.1": "An operational instruction, inspection checklist, or supplier requirement for a significant aspect.",
    "8.2": "An emergency response plan, a spill drill record, and any actions following the drill.",
    "9.1": "Monitoring results, measurement methods, and a record of how the results were evaluated.",
    "9.2": "An internal audit programme, audit criteria, findings, and follow-up records.",
    "9.3": "Management review minutes showing the information considered and decisions made.",
    "10.2": "A nonconformity record with cause analysis, assigned corrective actions, and an effectiveness check.",
}


def practical_guidance(number, summary):
    guidance, examples = GUIDANCE.get(number.split(".", 1)[0], ("Review how this topic applies to the organization and record the actions and responsibilities involved.", "Relevant procedures, records, decisions and follow-up actions."))
    matching_topics = [key for key in TOPIC_EXAMPLES if number == key or number.startswith(key + ".")]
    if matching_topics:
        examples = TOPIC_EXAMPLES[max(matching_topics, key=len)]
    entry = next((item for item in CLAUSES if item[0] == number), None)
    terms = entry[3] if entry else ""
    if terms:
        examples += "\n\nUseful search topics: %s." % terms
    return ("%s\n\nIn practice: %s\n\nReview whether the record is current, applies to the organization's scope, and shows who is responsible or what action was taken." % (summary, guidance)).strip(), examples

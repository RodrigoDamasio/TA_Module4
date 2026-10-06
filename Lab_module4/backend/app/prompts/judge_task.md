# Question
{question}

# Reference answer (ground truth)
{expected_answer}

# Excerpts the system retrieved (the only evidence it had)
{excerpts}

# Answer to grade
{answer}

# Score each from 1 to 5, with a one-sentence reason
- faithfulness: are all claims supported by the excerpts? (1 = many unsupported claims,
  5 = fully supported)
- relevance: does it address the question? (1 = irrelevant, 5 = directly answers it)
- correctness: does it agree with the reference answer? (1 = wrong, 3 = partially correct,
  5 = fully correct)

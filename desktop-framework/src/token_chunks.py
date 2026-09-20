"""Lossless character spans sized by the actual fast tokenizer, no truncation."""
import hashlib,bisect

RULE='token-span-v2-512-overlap64'
def split(text,tokenizer,budget=512,overlap=64):
    start=0;previous_end=0
    encoded=tokenizer(text,add_special_tokens=False,return_offsets_mapping=True,truncation=False,verbose=False)
    offsets=encoded['offset_mapping'];ends=[p[1] for p in offsets]
    capacity=budget-tokenizer.num_special_tokens_to_add(pair=False)
    if capacity<=overlap:raise ValueError('Token budget must exceed overlap and special tokens')
    while start<len(text):
        # Offset mappings preserve exact source text, including formula punctuation.
        first=bisect.bisect_right(ends,start)
        if len(offsets)-first<=capacity:end=len(text)
        else:
            end=offsets[first+capacity-1][1]
            paragraph=text.rfind('\n',start,end)
            if paragraph>start+(end-start)*.65:end=paragraph+1
        while len(tokenizer(text[start:end],add_special_tokens=True,truncation=False)['input_ids'])>budget:
            end-=1
        if end<=start:raise ValueError('Tokenizer cannot produce a bounded nonempty span')
        content=text[start:end];count=len(tokenizer(content,add_special_tokens=True,truncation=False)['input_ids'])
        yield {'start':start,'end':end,'text':content,'tokens':count,'overlap_chars':max(0,previous_end-start),'content_hash':hashlib.sha256(content.encode()).hexdigest(),'rule':RULE}
        if end==len(text):break
        used=tokenizer(content,add_special_tokens=False,return_offsets_mapping=True,truncation=False)['offset_mapping']
        next_start=start+used[max(0,len(used)-overlap)][0] if overlap else end
        previous_end=end;start=max(start+1,next_start)

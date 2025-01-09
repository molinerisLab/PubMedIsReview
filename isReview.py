#!/usr/bin/env python3

import sys
import argparse
import requests
import xml.etree.ElementTree as ET

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Check if PubMed articles (by title+year) are review or original, "
            "and if a given author is present. "
            "Input format: Each line should contain 'author_surname', 'title', and 'year' separated by tabs."
        )
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Email address (required by NCBI E-utilities)."
    )
    parser.add_argument(
        "--author",
        required=False,
        help=(
            "Override the author surname from the input lines. "
            "If provided, the script will use this author for all lookups."
        )
    )
    #verbose option
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print verbose output."
    )

    return parser.parse_args()

def split_title_to_query(title):
    """
    Split the title into words and return a list of words for the query.
    Example:
    Protein and Chemical Determinants of K-1249 Action and Selectivity for K-3P Channels
    became:
    "Protein"[Title] AND "Chemical"[Title] AND "Determinants"[Title] AND "Action"[Title] AND "Selectivity"[Title] AND "Channels"[Title] AND 2018[dp]
    """
    words = title.split()
    return ' AND '.join(f'"{w}"[Title]' for w in words)

def fetch_pubmed_data(title, year, email):
    """
    Given an article title, year, and user email,
    1) Query PubMed via ESearch for the first match.
    2) If found, EFetch the article metadata in XML.
    
    Returns tuple (pmid, XML) or (None, None) if not found.
    """
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"



    # 1) ESearch: find PMIDs for the given title and year
    title_query_splitted = split_title_to_query(title)
    #query = f'"{title_query_splitted}"[Title] AND {year}[dp]'
    query = f"{title}[Title] AND {year}[dp]"
    esearch_params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": 10,
        "email": email
    }
    
    r = requests.get(base_url + "esearch.fcgi", params=esearch_params)
    #output in stderr the complete url queried if verbose
    if args.verbose:
        print(r.url, file=sys.stderr)
        #print the response status code
        print(r.status_code, file=sys.stderr)
        #print the response content
        print(r.content, file=sys.stderr)

    r.raise_for_status()
    
    data = r.json()
    pmid_list = data.get("esearchresult", {}).get("idlist", [])

    # Check for warnings in the response and print them if any
    warnings = data.get("esearchresult", {}).get("warnings", [])
    if warnings:
        for warning in warnings:
            print(f"Warning from PubMed: {warning}", file=sys.stderr)

    if len(pmid_list) > 1:
        print("Warning: More than one result found. Using the first result.", file=sys.stderr)
        warnings.append("More than one result found. Using the first result.")
    
    if len(pmid_list) == 0:
        warnings.append("No results found.")

    if not pmid_list:
        return None, None, warnings
    
    pmid = pmid_list[0]

    # 2) EFetch: retrieve full article XML
    efetch_params = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml",
        "email": email
    }
    r2 = requests.get(base_url + "efetch.fcgi", params=efetch_params)
    r2.raise_for_status()
    
    return pmid, r2.text, warnings


def get_authors_and_pubtypes(article_xml):
    """
    Parse the EFetch XML to extract:
      - A list of all author surnames
      - A list of publication types
    Returns ( [author_surnames], [pubtypes] ).
    """
    root = ET.fromstring(article_xml)
    
    author_surnames = []
    pub_types = []
    
    # The structure is PubmedArticle -> MedlineCitation -> Article
    # Authors: ./PubmedArticle/MedlineCitation/Article/AuthorList/Author
    #   <LastName>Smith</LastName>
    # Publication types: ./PubmedArticle/MedlineCitation/Article/PublicationTypeList/PublicationType
    for pubmed_article in root.findall("./PubmedArticle"):
        medline_citation = pubmed_article.find("MedlineCitation")
        if medline_citation is None:
            continue
        
        article = medline_citation.find("Article")
        if article is None:
            continue
        
        # Extract authors
        author_list = article.find("AuthorList")
        if author_list is not None:
            for author in author_list.findall("Author"):
                last_name_el = author.find("LastName")
                if last_name_el is not None:
                    author_surnames.append(last_name_el.text)
        
        # Extract publication types
        pubtype_list = article.find("PublicationTypeList")
        if pubtype_list is not None:
            for pt in pubtype_list.findall("PublicationType"):
                if pt.text:
                    pub_types.append(pt.text)
                    
    return author_surnames, pub_types


def determine_article_type(pmid, xml_data, author_surname):
    """
    High-level function:
      - Query PubMed for (title+year),
      - Fetch authors & pubtypes,
      - Check if 'author_surname' is in authors,
      - Return 'review', 'original', or 'not_found'.
    """
    
    authors, pubtypes = get_authors_and_pubtypes(xml_data)
    
    # Check if the provided surname is among the authors (case-insensitive match).
    lower_surname = author_surname.strip().lower()
    lower_authors = [a.strip().lower() for a in authors]

    if lower_surname not in lower_authors:
        return("not_found", "Specified author not found in the article.")
    
    # If the author is found, check if "Review" is in the pubtypes
    if any(pt.lower() == "review" for pt in pubtypes):
        return("review", "")
    else:
        return("original", "")


def main():
    global args
    args = parse_args()
    
    # Read from stdin line by line.
    # Each line has: author_surname, title, year (tab-separated).
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        
        try:
            parts = line.split("\t")
            if args.author:
                author_surname = args.author
                title, pub_year = parts
            else:
                author_surname, title, pub_year = parts
        except ValueError:
            print(f"Error: Invalid input line: {line}\n{parts}", file=sys.stderr)
            #raise the original exception and exit
            raise


        # Determine if this paper is a Review, Original, or not found
        pmid, xml_data, warnings = fetch_pubmed_data(title, pub_year, args.email)
        if not pmid or not xml_data:
            art_type="not_found"
        else:
            art_type, warnings2 = determine_article_type(pmid, xml_data, author_surname)
            if warnings2:
                warnings.append(warnings2)
        warnings = "|".join(warnings)

        # Print the original line + one extra column
        #   “review”, “original”, or “not_found”
        #
        # Note: The first column in the output is still the original
        # author_surname from stdin (as per your requirements).
        print(f"{author_surname}\t{title}\t{pub_year}\t{art_type}\t{warnings}\thttps://pubmed.ncbi.nlm.nih.gov/?term={title}&sort=date")


if __name__ == "__main__":
    main()

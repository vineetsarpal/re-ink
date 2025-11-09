"""
Service layer for integrating with LandingAI's Agentic Document Extraction API.
Handles document upload, extraction job management, and result parsing.
"""
import httpx
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from app.core.config import settings

logger = logging.getLogger(__name__)


class LandingAIService:
    """
    Service for interacting with LandingAI Document Extraction API.
    """

    def __init__(self):
        self.api_url = settings.LANDINGAI_API_URL
        self.api_key = settings.LANDINGAI_API_KEY
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def submit_document_for_extraction(
        self,
        file_path: str,
        extraction_schema: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Submit a document to LandingAI for extraction.

        Args:
            file_path: Path to the document file
            extraction_schema: Optional schema defining what fields to extract

        Returns:
            Dictionary containing job_id and status information

        Raises:
            httpx.HTTPError: If the API request fails
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Read the file
                file_path_obj = Path(file_path)

                with open(file_path_obj, "rb") as f:
                    files = {
                        "file": (file_path_obj.name, f, self._get_content_type(file_path_obj))
                    }

                    # Prepare the extraction request
                    data = {
                        "extraction_type": "reinsurance_contract",
                        "include_parties": True
                    }

                    if extraction_schema:
                        data["schema"] = extraction_schema

                    # Submit to LandingAI API
                    # Note: This is a placeholder - adjust according to actual LandingAI API spec
                    response = await client.post(
                        f"{self.api_url}/submit",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        files=files,
                        data=data
                    )
                    response.raise_for_status()

                    result = response.json()
                    logger.info(f"Document submitted successfully. Job ID: {result.get('job_id')}")
                    return result

        except httpx.HTTPError as e:
            logger.error(f"LandingAI API request failed: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error submitting document: {str(e)}")
            raise

    async def get_extraction_status(self, job_id: str) -> Dict[str, Any]:
        """
        Check the status of an extraction job.

        Args:
            job_id: The job ID returned from submit_document_for_extraction

        Returns:
            Dictionary containing job status and results if complete

        Raises:
            httpx.HTTPError: If the API request fails
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.api_url}/status/{job_id}",
                    headers=self.headers
                )
                response.raise_for_status()

                result = response.json()
                logger.info(f"Job {job_id} status: {result.get('status')}")
                return result

        except httpx.HTTPError as e:
            logger.error(f"Failed to get extraction status: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error getting extraction status: {str(e)}")
            raise

    async def get_extraction_results(self, job_id: str) -> Dict[str, Any]:
        """
        Retrieve the extraction results for a completed job.

        Args:
            job_id: The job ID returned from submit_document_for_extraction

        Returns:
            Dictionary containing extracted contract and party data

        Raises:
            httpx.HTTPError: If the API request fails
            ValueError: If job is not complete
        """
        try:
            # First check if job is complete
            status = await self.get_extraction_status(job_id)

            if status.get("status") != "completed":
                raise ValueError(f"Job {job_id} is not complete. Current status: {status.get('status')}")

            # Get the results
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.api_url}/results/{job_id}",
                    headers=self.headers
                )
                response.raise_for_status()

                results = response.json()
                logger.info(f"Successfully retrieved results for job {job_id}")
                return results

        except httpx.HTTPError as e:
            logger.error(f"Failed to get extraction results: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error getting extraction results: {str(e)}")
            raise

    def parse_extraction_results(self, raw_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse and structure the raw extraction results from LandingAI.

        Args:
            raw_results: Raw results from LandingAI API

        Returns:
            Structured dictionary with contract_data and parties_data
        """
        # This is a placeholder implementation
        # Actual parsing logic will depend on LandingAI's response format

        try:
            extracted_data = raw_results.get("extracted_data", {})

            # Parse contract data
            contract_data = {
                "contract_number": extracted_data.get("contract_number"),
                "contract_name": extracted_data.get("contract_name"),
                "contract_type": extracted_data.get("contract_type"),
                "effective_date": extracted_data.get("effective_date"),
                "expiration_date": extracted_data.get("expiration_date"),
                "premium_amount": extracted_data.get("premium_amount"),
                "currency": extracted_data.get("currency", "USD"),
                "limit_amount": extracted_data.get("limit_amount"),
                "coverage_territory": extracted_data.get("coverage_territory"),
                "line_of_business": extracted_data.get("line_of_business"),
            }

            # Parse parties data
            parties_data = extracted_data.get("parties", [])

            # Include confidence score
            confidence_score = raw_results.get("confidence_score")

            return {
                "contract_data": contract_data,
                "parties_data": parties_data,
                "confidence_score": confidence_score,
                "extraction_metadata": raw_results.get("metadata", {})
            }

        except Exception as e:
            logger.error(f"Error parsing extraction results: {str(e)}")
            raise

    @staticmethod
    def _get_content_type(file_path: Path) -> str:
        """Determine content type based on file extension."""
        suffix = file_path.suffix.lower()
        content_types = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword"
        }
        return content_types.get(suffix, "application/octet-stream")


# Singleton instance
landingai_service = LandingAIService()
